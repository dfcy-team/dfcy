import pytest
from rest_framework.test import APIClient

from apps.supply_chain import services
from apps.supply_chain.dates import business_date
from tests.test_supply_chain_v2_foundation import confirmed_order, freight, internal_user, po_payload, shipment_payload, world
from apps.supply_chain.models import domain_write
from apps.tenants.models import Tenant

BASE = "/api/internal/supply-chain/v2/"


@pytest.mark.django_db
def test_payment_terms_adjustment_is_audited_versioned_and_idempotent(world):
    actor = internal_user(world, "terms-api-adjust")
    today = business_date()
    world["supplier"].payment_term_days = 14
    world["supplier"].payment_term_start = "shipment_date"
    world["supplier"].payment_reminder_days = 3
    world["supplier"].save(update_fields=["payment_term_days", "payment_term_start", "payment_reminder_days"])
    order = confirmed_order(world, actor, key="terms-api-po", payload=po_payload(
        world, number="PO-TERMS-API", order_date=today,
    ))
    shipment = services.create_supplier_shipment(actor, shipment_payload(
        world, order, "terms-api-shipment", number="SH-TERMS-API", shipment_date=today,
    ), idempotency_key="terms-api-shipment")
    client = APIClient()
    client.force_authenticate(actor)
    path = BASE + f"costs/shipment/{shipment.pk}/payment-terms/"

    initial = client.get(path)
    assert initial.status_code == 200
    assert initial.data["data"]["version"] == 0
    assert initial.data["data"]["days"] == 14
    assert initial.data["data"]["reminder_days"] == 3
    world["supplier"].payment_term_days = 90
    world["supplier"].save(update_fields=["payment_term_days"])
    assert client.get(path).data["data"]["days"] == 14

    payload = {"days": 0, "start": "reconciliation_date", "reminder_days": 0,
        "reconciliation_date": today.isoformat(), "due_date_override": None,
        "reason": "供应商确认账单日期", "expected_version": 0}
    headers = {"HTTP_IDEMPOTENCY_KEY": "terms-api-adjust"}
    saved = client.put(path, payload, format="json", **headers)
    assert saved.status_code == 200, saved.data
    assert saved.data["data"]["anchor_date"] == today.isoformat()
    assert saved.data["data"]["due_date"] == today.isoformat()
    assert saved.data["data"]["version"] == 1
    assert len(saved.data["data"]["history"]) == 1

    replay = client.put(path, payload, format="json", **headers)
    assert replay.status_code == 200
    assert replay.data["data"]["version"] == 1
    changed = {**payload, "days": 5}
    rejected = client.put(path, changed, format="json", **headers)
    assert rejected.status_code == 422
    conflict = {**payload, "expected_version": 0, "reconciliation_date": None}
    conflict_response = client.put(path, conflict, format="json", HTTP_IDEMPOTENCY_KEY="terms-api-new-key")
    assert conflict_response.status_code == 400


@pytest.mark.django_db
def test_payment_terms_reject_unsupported_kind_without_server_error(world):
    actor = internal_user(world, "terms-api-kind")
    client = APIClient()
    client.force_authenticate(actor)
    response = client.get(BASE + "costs/purchase/1/payment-terms/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_readonly_user_cannot_change_terms(world):
    owner = internal_user(world, "terms-api-owner")
    reader = internal_user(world, "terms-api-reader", codes=("supply.v2.view",))
    today = business_date()
    order = confirmed_order(world, owner, key="terms-api-readonly-po", payload=po_payload(
        world, number="PO-TERMS-READONLY", order_date=today,
    ))
    shipment = services.create_supplier_shipment(owner, shipment_payload(
        world, order, "terms-api-readonly-shipment", number="SH-TERMS-READONLY", shipment_date=today,
    ), idempotency_key="terms-api-readonly-shipment")
    client = APIClient()
    client.force_authenticate(reader)
    path = BASE + f"costs/shipment/{shipment.pk}/payment-terms/"
    response = client.put(path, {"days": 2, "start": "shipment_date", "reason": "x", "expected_version": 0},
        format="json", HTTP_IDEMPOTENCY_KEY="terms-api-readonly")
    assert response.status_code in (403, 404)


@pytest.mark.django_db
def test_other_tenant_cannot_read_terms(world):
    owner = internal_user(world, "terms-api-cross-owner")
    today = business_date()
    order = confirmed_order(world, owner, key="terms-api-cross-po", payload=po_payload(
        world, number="PO-TERMS-CROSS", order_date=today,
    ))
    shipment = services.create_supplier_shipment(owner, shipment_payload(
        world, order, "terms-api-cross-shipment", number="SH-TERMS-CROSS", shipment_date=today,
    ), idempotency_key="terms-api-cross-shipment")
    other_world = {"tenant": Tenant.objects.create(name="Other tenant", code="terms-other")}
    stranger = internal_user(other_world, "terms-api-stranger")
    client = APIClient()
    client.force_authenticate(stranger)
    response = client.get(BASE + f"costs/shipment/{shipment.pk}/payment-terms/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_archive_update_without_reminder_days_preserves_existing_value(world):
    actor = internal_user(world, "terms-api-archive-preserve")
    supplier = world["supplier"]
    supplier.payment_reminder_days = 4
    supplier.save(update_fields=["payment_reminder_days"])
    client = APIClient()
    client.force_authenticate(actor)
    response = client.patch(BASE + f"suppliers/{supplier.pk}/", {
        "name": supplier.name + " edited", "expected_version": supplier.supply_version,
    }, format="json", HTTP_IDEMPOTENCY_KEY="terms-api-archive-preserve")
    assert response.status_code == 200, response.data
    supplier.refresh_from_db()
    assert supplier.payment_reminder_days == 4


@pytest.mark.django_db
def test_carrier_terms_are_frozen_on_batch_creation(world):
    actor = internal_user(world, "terms-api-carrier")
    carrier = freight(world)
    carrier.payment_term_days = 12
    carrier.payment_term_start = "warehouse_arrival"
    carrier.payment_reminder_days = 4
    with domain_write():
        carrier.save(update_fields=["payment_term_days", "payment_term_start", "payment_reminder_days"])
    today = business_date()
    order = confirmed_order(world, actor, key="terms-api-carrier-po", payload=po_payload(
        world, number="PO-TERMS-CARRIER", order_date=today,
    ))
    shipment = services.create_supplier_shipment(actor, shipment_payload(
        world, order, "terms-api-carrier-shipment", number="SH-TERMS-CARRIER", shipment_date=today,
    ), idempotency_key="terms-api-carrier-shipment")
    batch = services.create_dispatch_batch(actor, {"number": "DB-TERMS-CARRIER", "freight_company_id": carrier.pk,
        "freight_number": "F-TERMS-CARRIER", "shipment_ids": [shipment.pk]}, idempotency_key="terms-api-carrier-batch")
    carrier.payment_term_days = 90
    with domain_write():
        carrier.save(update_fields=["payment_term_days"])
    assert batch.freight_terms_snapshot == {"days": 12, "start": "warehouse_arrival", "reminder_days": 4}


@pytest.mark.django_db
def test_shipment_and_domestic_freight_terms_are_independent(world):
    actor = internal_user(world, "terms-api-domestic")
    world["supplier"].payment_term_days = 30
    world["supplier"].payment_term_start = "shipment_date"
    world["supplier"].save(update_fields=["payment_term_days", "payment_term_start"])
    carrier = freight(world)
    carrier.service_scopes = ["domestic"]
    carrier.payment_term_days = 5
    carrier.payment_term_start = "collection_arrival"
    with domain_write():
        carrier.save(update_fields=["service_scopes", "payment_term_days", "payment_term_start"])
    today = business_date()
    order = confirmed_order(world, actor, key="terms-api-independent-po", payload=po_payload(
        world, number="PO-TERMS-INDEPENDENT", order_date=today,
    ))
    shipment = services.create_supplier_shipment(actor, shipment_payload(
        world, order, "terms-api-independent-shipment", number="SH-TERMS-INDEPENDENT", shipment_date=today,
    ), idempotency_key="terms-api-independent-shipment")
    from apps.supply_chain.shipments import save_domestic_transport
    shipment = save_domestic_transport(actor, shipment.pk, {"expected_version": shipment.version,
        "domestic_carrier_id": carrier.pk, "domestic_tracking_number": "TRK"}, "terms-api-transport")
    client = APIClient()
    client.force_authenticate(actor)
    goods = client.get(BASE + f"costs/shipment/{shipment.pk}/payment-terms/").data["data"]
    domestic = client.get(BASE + f"costs/domestic_freight/{shipment.pk}/payment-terms/").data["data"]
    assert goods["days"] == 30
    assert domestic["days"] == 5
    assert goods["version"] == domestic["version"] == 0
