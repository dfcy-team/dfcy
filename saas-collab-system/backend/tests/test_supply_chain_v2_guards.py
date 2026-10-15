"""Additional database and authentication boundaries for phase 1."""
import pytest
from django.db import IntegrityError, connection, transaction
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.supply_chain import services
from apps.supply_chain.models import DispatchMembership, PurchaseLine
from tests.test_supply_chain_v2_foundation import (
    world, confirmed_order, freight, internal_user, po_payload, shipment_payload,
)


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5])
def test_invalid_quantities_do_not_leave_partial_orders(world, quantity):
    from django.core.exceptions import ValidationError
    from apps.supply_chain.models import PurchaseOrder
    buyer = internal_user(world)
    payload = po_payload(world, lines=[{"sku_id": world["sku"].pk, "quantity": quantity, "unit_price": "1"}])
    with pytest.raises(ValidationError):
        services.create_purchase_order(buyer, payload, idempotency_key="invalid-quantity")
    assert PurchaseOrder.objects.count() == 0


def test_database_constraints_block_duplicate_active_members_and_zero_quantities(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, "guard"), idempotency_key="guard")
    carrier = freight(world)
    batch = services.create_dispatch_batch(buyer, {"number": "DB-GUARD", "freight_company_id": carrier.pk, "freight_number": "F", "shipment_ids": [shipment.pk]}, idempotency_key="batch-guard")
    member = DispatchMembership.objects.get(batch=batch)
    table = connection.ops.quote_name(DispatchMembership._meta.db_table)
    fields = "tenant_id, created_by_id, created_at, updated_at, version, batch_id, shipment_id, active_guard"
    # Bypass Python model validation to exercise the migration's actual DB guard.
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {table} ({fields}) SELECT {fields} FROM {table} WHERE id=%s", [member.pk])
    line = order.lines.get()
    line_table = connection.ops.quote_name(PurchaseLine._meta.db_table)
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {line_table} SET quantity=%s WHERE id=%s", [0, line.pk])
    assert DispatchMembership.objects.filter(shipment=shipment, active_guard=True).count() == 1
    line.refresh_from_db()
    assert line.quantity == 10


def test_miniapp_token_and_inactive_procurement_cannot_read_internal_api(world):
    buyer = internal_user(world)
    refresh = RefreshToken.for_user(buyer)
    refresh["channel"] = "miniapp"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    assert client.get("/api/internal/supply-chain/v2/purchase-orders/").status_code == 403
    buyer.is_active = False
    buyer.save(update_fields=["is_active"])
    client = APIClient()
    client.force_authenticate(user=buyer)
    assert client.get("/api/internal/supply-chain/v2/contract/").status_code == 403


def test_unregistered_and_legacy_order_scope_dimensions_grant_no_new_orders(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    legacy_scope_user = internal_user(world, "legacy-scope", scope="custom", config={"supply_purchase_order_ids": [order.pk], "supply_chain_order_ids": [order.pk]})
    client = APIClient()
    client.force_authenticate(user=legacy_scope_user)
    response = client.get("/api/internal/supply-chain/v2/purchase-orders/")
    assert response.status_code == 200 and response.json()["data"] == []
