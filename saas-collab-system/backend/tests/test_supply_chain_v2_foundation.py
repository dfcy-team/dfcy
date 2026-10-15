"""Isolation and state-machine tests for the executable supply-chain v2 foundation."""
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from importlib import import_module
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import connection
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.masterdata.models import CountrySiteMaster, SupplierMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import PurchaseOrder as LegacyPurchaseOrder
from apps.commerce.models import InventorySnapshot
from apps.tenants.models import Tenant
from apps.supply_chain import services
register_v2_permissions = import_module("apps.supply_chain.migrations.0002_register_permissions").register
from apps.supply_chain.models import (
    BusinessEvent, DispatchBatch, DispatchMembership, FreightCompany, InboundLine,
    InboundOrder, NotificationOutbox, PurchaseOrder, ShipmentLine, SupplierShipment,
    domain_write,
)


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="SC2 isolation", code="sc2-isolation")
    country = CountrySiteMaster.objects.create(tenant=tenant, code="us", name="USA", country_code="US")
    country_ca = CountrySiteMaster.objects.create(tenant=tenant, code="ca", name="Canada", country_code="CA")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="supplier-a", name="Supplier A")
    supplier_b = SupplierMaster.objects.create(tenant=tenant, code="supplier-b", name="Supplier B")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SC2-SPU", product_name="Widget")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SC2-SKU")
    sku_b = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SC2-SKU-B")
    return locals()


def internal_user(world, username="buyer", scope=DataScope.ScopeType.ALL, config=None, codes=("supply.v2.view", "supply.v2.manage")):
    user = CustomUser.objects.create_user(username=username, tenant=world["tenant"], user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=world["tenant"], code=f"role-{username}", name="Supply v2")
    perms = []
    for code in codes:
        perm, _ = Permission.objects.update_or_create(code=code, defaults={"name": code, "module": "supply", "action": code.rsplit(".", 1)[-1], "description": "v2 test"})
        perms.append(perm)
    role.permissions.add(*perms)
    UserRole.objects.create(tenant=world["tenant"], user=user, role=role)
    DataScope.objects.create(tenant=world["tenant"], role=role, scope_type=scope, config=config or {})
    return user


def supplier_user(world, supplier, username):
    user = CustomUser.objects.create_user(username=username, tenant=world["tenant"], user_type=CustomUser.UserType.EXTERNAL)
    ExternalUserProfile.objects.create(user=user, tenant=world["tenant"], supplier_id=supplier.pk, company_name=supplier.name)
    return user


def po_payload(world, key="po-key", *, source="manual", lines=None, supplier=None, country=None, number="PO-1", **extra):
    return {"number": number, "supplier_id": (supplier or world["supplier"]).pk,
            "country_id": (country or world["country"]).pk, "source_kind": source,
            "order_date": date(2026, 10, 12), "lines": lines or [{"sku_id": world["sku"].pk, "quantity": 10, "unit_price": "2.5"}], **extra}


def confirmed_order(world, user, *, key="po", payload=None):
    order = services.create_purchase_order(user, payload or po_payload(world, key), idempotency_key=key)
    return services.confirm_purchase_order(user, order.pk, expected_version=order.version, idempotency_key=f"confirm-{key}")


def shipment_payload(world, order, key, *, number="SH-1", lines=None, **extra):
    return {"order_id": order.pk, "number": number, "shipment_date": date(2026, 10, 12),
            "lines": lines or [{"sku_id": world["sku"].pk, "quantity": 4}], **extra}


def freight(world):
    with domain_write():
        return FreightCompany.objects.create(tenant=world["tenant"], created_by=internal_user(world, "freight-owner"), code="carrier", name="Carrier", shipping_marks="MARK")


def test_purchase_sources_idempotency_optional_reference_and_allocation_rollback(world):
    buyer = internal_user(world)
    payloads = [
        po_payload(world, source="manual", number="PO-M", reference_number=""),
        po_payload(world, source="operating", number="PO-O", lines=[{"sku_id": world["sku"].pk, "quantity": 3, "unit_price": "1", "operating_sources":[{"system":"ops", "order_id":"o1", "line_id":"l1", "quantity":3}]}]),
        po_payload(world, source="import", number="PO-I", import_batch_ref="batch-1", lines=[{"sku_id": world["sku"].pk, "quantity": 2, "unit_price":"1", "import_row_number":8}]),
    ]
    records = [services.create_purchase_order(buyer, p, idempotency_key=f"k{i}") for i, p in enumerate(payloads)]
    assert [r.source_kind for r in records] == ["manual", "operating", "import"]
    assert records[0].reference_number == ""
    repeated_ref = services.create_purchase_order(buyer, po_payload(world, number="PO-REF-2", reference_number="REF-SHARED"), idempotency_key="ref-2")
    services.create_purchase_order(buyer, po_payload(world, number="PO-REF-3", reference_number="REF-SHARED"), idempotency_key="ref-3")
    assert repeated_ref.reference_number == "REF-SHARED"
    assert services.create_purchase_order(buyer, payloads[0], idempotency_key="k0").pk == records[0].pk
    with pytest.raises(DjangoValidationError):
        services.create_purchase_order(buyer, po_payload(world, number="PO-OTHER"), idempotency_key="k0")
    before = PurchaseOrder.objects.count()
    with pytest.raises(DjangoValidationError):
        services.create_purchase_order(buyer, po_payload(world, source="operating", number="PO-BAD", lines=[{"sku_id":world["sku"].pk,"quantity":4,"operating_sources":[{"system":"ops","order_id":"o","line_id":"l","quantity":3}]}]), idempotency_key="bad-allocation")
    assert PurchaseOrder.objects.count() == before
    assert not PurchaseOrder.objects.filter(number="PO-BAD").exists()


def test_confirmation_price_version_and_atomic_blocked_outbox(world):
    buyer = internal_user(world)
    order = services.create_purchase_order(buyer, po_payload(world, number="PO-PRICE", lines=[{"sku_id":world["sku"].pk,"quantity":1}]), idempotency_key="price")
    with pytest.raises(DjangoValidationError):
        services.confirm_purchase_order(buyer, order.pk, expected_version=1, idempotency_key="premature")
    order = services.create_purchase_order(buyer, po_payload(world, number="PO-CONFIRM"), idempotency_key="confirm-create")
    result = services.confirm_purchase_order(buyer, order.pk, expected_version=1, idempotency_key="confirmed")
    assert result.status == "confirmed" and result.version == 2
    assert list(NotificationOutbox.objects.filter(order=result).values_list("status", "blocked_reason")) == [("blocked", "channel_not_verified")]
    assert NotificationOutbox.objects.filter(order=result).count() == 1
    assert services.confirm_purchase_order(buyer, result.pk, expected_version=1, idempotency_key="confirmed").pk == result.pk
    with pytest.raises(DjangoValidationError):
        services.confirm_purchase_order(buyer, result.pk, expected_version=1, idempotency_key="stale")


def test_supplier_and_procurement_share_shipments_excess_additional_and_supplier_isolation(world):
    buyer = internal_user(world)
    buyer_b = internal_user(world, "buyer-b")
    order = confirmed_order(world, buyer, key="shared", payload=po_payload(world, number="PO-SHARED", lines=[{"sku_id":world["sku"].pk,"quantity":5,"unit_price":"3"}]))
    ext = supplier_user(world, world["supplier"], "supplier-own")
    other = supplier_user(world, world["supplier_b"], "supplier-other")
    shipment = services.create_supplier_shipment(ext, shipment_payload(world, order, "supplier-sh", number="SH-SUP", lines=[{"sku_id":world["sku"].pk,"quantity":4}]), idempotency_key="supplier-sh")
    before_supplier_pricing_attempt = SupplierShipment.objects.filter(order=order).count()
    with pytest.raises(PermissionDenied):
        services.create_supplier_shipment(ext, shipment_payload(world, order, "supplier-price", number="SH-PRICE", lines=[{"sku_id":world["sku"].pk,"quantity":1,"unit_price":"99"}]), idempotency_key="supplier-price")
    assert SupplierShipment.objects.filter(order=order).count() == before_supplier_pricing_attempt
    assert shipment.status == "submitted"
    second = services.create_supplier_shipment(buyer, shipment_payload(world, order, "proc-sh", number="SH-PROC", lines=[{"sku_id":world["sku"].pk,"quantity":4,"unit_price":"3"},{"sku_id":world["sku_b"].pk,"quantity":2}]), idempotency_key="proc-sh")
    src = shipment.lines.get()
    add_line = second.lines.get(sku=world["sku_b"])
    excess_line = second.lines.get(sku=world["sku"])
    assert shipment.entry_mode == "supplier" and second.entry_mode == "procurement"
    assert excess_line.exception_type == "excess" and excess_line.excess_quantity == 3
    assert add_line.exception_type == "additional" and add_line.purchase_line_id is None
    assert src.purchase_price_snapshot == Decimal("3")
    foreign = confirmed_order(world, buyer, key="foreign", payload=po_payload(world, number="PO-FOREIGN", country=world["country_ca"]))
    with pytest.raises(DjangoValidationError):
        services.create_supplier_shipment(buyer, shipment_payload(world, foreign, "foreign-sh", lines=[{"sku_id":world["sku"].pk,"quantity":1,"purchase_line_id":order.lines.get().pk}]), idempotency_key="foreign-sh")
    with pytest.raises(NotFound):
        services.create_supplier_shipment(other, shipment_payload(world, order, "other-sh", lines=[{"sku_id":world["sku"].pk,"quantity":1,"unit_price":"9"}]), idempotency_key="other-sh")
    assert SupplierShipment.objects.filter(order=order).count() == 2


def test_dispatch_and_inbound_guards_draft_idempotency_and_no_inventory_write(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer, key="dispatch", payload=po_payload(world, number="PO-DISPATCH"))
    shipment1 = services.create_supplier_shipment(buyer, shipment_payload(world, order, "dispatch-sh1", number="SH-D1"), idempotency_key="dispatch-sh1")
    shipment2 = services.create_supplier_shipment(buyer, shipment_payload(world, order, "dispatch-sh2", number="SH-D2"), idempotency_key="dispatch-sh2")
    carrier = freight(world)
    ca_order = confirmed_order(world, buyer, key="ca", payload=po_payload(world, number="PO-CA", country=world["country_ca"]))
    ca_shipment = services.create_supplier_shipment(buyer, shipment_payload(world, ca_order, "ca-sh", number="SH-CA"), idempotency_key="ca-sh")
    with pytest.raises(DjangoValidationError):
        services.create_dispatch_batch(buyer, {"number":"DB-MIXED","freight_company_id":carrier.pk,"freight_number":"F-M","shipment_ids":[shipment1.pk,ca_shipment.pk]}, idempotency_key="mixed")
    services.mark_collection_arrival(buyer, shipment1.pk, expected_version=1, occurred_at=datetime(2026, 10, 12, 0, tzinfo=dt_timezone.utc), idempotency_key="collection-arrived")
    batch = services.create_dispatch_batch(buyer, {"number":"DB-1","freight_company_id":carrier.pk,"freight_number":"F-1","shipment_ids":[shipment1.pk, shipment2.pk]}, idempotency_key="batch1")
    member_arrivals = {m.shipment_id: m.shipment.collection_arrived for m in DispatchMembership.objects.filter(batch=batch).select_related("shipment")}
    assert member_arrivals == {shipment1.pk: True, shipment2.pk: False}
    with pytest.raises(DjangoValidationError):
        services.create_dispatch_batch(buyer, {"number":"DB-DUP","freight_company_id":carrier.pk,"freight_number":"F-D","shipment_ids":[shipment1.pk]}, idempotency_key="duplicate")
    with pytest.raises(DjangoValidationError):
        services.generate_inbound_draft(buyer, batch.pk, warehouse_id=1, expected_version=1, idempotency_key="too-early")
    times = [datetime(2026, 10, 12, h, tzinfo=dt_timezone.utc) for h in (1,2,3)]
    for stage, at, ver, key in (("departed",times[0],1,"dep"),("arrived_port",times[1],2,"port"),("arrived_warehouse",times[2],3,"wh")):
        batch = services.mark_logistics_stage(buyer,batch.pk,stage=stage,occurred_at=at,expected_version=ver,idempotency_key=key)
    assert not InboundOrder.objects.filter(batch=batch).exists(), "logistics arrival alone must not generate an inbound draft"
    dispatch_http = APIClient(); dispatch_http.force_authenticate(user=buyer)
    projected = dispatch_http.get("/api/internal/supply-chain/v2/supplier-shipments/").json()["data"]
    assert {row["number"]: row["logistics_stage"] for row in projected}["SH-D1"] == "arrived_warehouse"
    assert {row["number"]: row["logistics_stage"] for row in projected}["SH-CA"] == "unmarked"
    wrong = WarehouseMaster.objects.create(tenant=world["tenant"], code="ca-wh", name="CA", country_code="CA", warehouse_type="owned")
    inactive = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-off", name="Inactive", country_code="US", warehouse_type="owned", status="inactive")
    for warehouse in (wrong, inactive):
        with pytest.raises(DjangoValidationError):
            services.generate_inbound_draft(buyer,batch.pk,warehouse_id=warehouse.pk,expected_version=4,idempotency_key=f"bad-{warehouse.pk}")
    warehouse = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-wh", name="US", country_code="US", warehouse_type="owned")
    inbound = services.generate_inbound_draft(buyer,batch.pk,warehouse_id=warehouse.pk,expected_version=4,idempotency_key="draft")
    assert services.generate_inbound_draft(buyer,batch.pk,warehouse_id=warehouse.pk,expected_version=4,idempotency_key="draft").pk == inbound.pk
    assert inbound.status == "draft" and inbound.lines.count() == 2
    assert all(line.received_quantity is None for line in InboundLine.objects.filter(inbound=inbound))
    assert InventorySnapshot.objects.count() == 0


def test_http_scope_read_only_contract_flags_and_legacy_models_unchanged(world):
    buyer = internal_user(world, "http-owner", scope=DataScope.ScopeType.OWN)
    other_buyer = internal_user(world, "http-other")
    own = confirmed_order(world,buyer,key="http-own",payload=po_payload(world,number="PO-HTTP-OWN"))
    hidden = confirmed_order(world,other_buyer,key="http-hidden",payload=po_payload(world,number="PO-HTTP-HIDDEN",supplier=world["supplier_b"]))
    ext = supplier_user(world,world["supplier"],"http-supplier")
    client = APIClient(); client.force_authenticate(user=buyer)
    legacy_before = list(LegacyPurchaseOrder.objects.values_list("pk", flat=True))
    inventory_before = list(InventorySnapshot.objects.values_list("pk", flat=True))
    response = client.get("/api/internal/supply-chain/v2/purchase-orders/")
    assert response.status_code == 200 and [x["id"] for x in response.json()["data"]] == [own.pk]
    assert response.json()["data"][0]["prices_complete"] is True
    contract = client.get("/api/internal/supply-chain/v2/contract/").json()["data"]
    assert contract["capabilities"]["read_api"] and contract["capabilities"]["transactional_domain_commands"]
    assert contract["capabilities"]["http_write_api"] is True
    assert "procurement_orders" in contract["capabilities"]["write_api_scope"]
    assert contract["capabilities"]["automatic_external_group_delivery"] is False
    assert contract["notification"]["channel_status"] == "not_verified"
    from apps.accounts.external_auth import issue_supplier_web_tokens
    supplier_client = APIClient()
    supplier_client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_supplier_web_tokens(ext)["access"])
    supplier_rows = supplier_client.get("/api/external/supplier/supply-chain/v2/purchase-orders/").json()["data"]
    assert [x["id"] for x in supplier_rows] == [own.pk]
    assert hidden.pk not in [x["id"] for x in supplier_rows]
    draft = services.create_purchase_order(buyer, po_payload(world, number="PO-DRAFT-SUPPLIER"), idempotency_key="http-draft")
    supplier_rows = supplier_client.get("/api/external/supplier/supply-chain/v2/purchase-orders/").json()["data"]
    assert draft.pk not in [x["id"] for x in supplier_rows]
    assert supplier_client.post("/api/external/supplier/supply-chain/v2/purchase-orders/", {}, format="json").status_code == 405
    custom = internal_user(world, "http-custom", scope=DataScope.ScopeType.CUSTOM, config={"supplier_ids": [world["supplier_b"].pk]})
    custom_client = APIClient(); custom_client.force_authenticate(user=custom)
    custom_ids = [x["id"] for x in custom_client.get("/api/internal/supply-chain/v2/purchase-orders/").json()["data"]]
    assert hidden.pk in custom_ids and own.pk not in custom_ids
    a_shipment = services.create_supplier_shipment(buyer, shipment_payload(world, own, "own-supplier-sh", number="SH-OWN-SCOPE"), idempotency_key="own-supplier-sh")
    b_shipment = services.create_supplier_shipment(other_buyer, shipment_payload(world, hidden, "other-supplier-sh", number="SH-OTHER-SCOPE"), idempotency_key="other-supplier-sh")
    carrier = freight(world)
    mixed_batch = services.create_dispatch_batch(other_buyer, {"number":"DB-CUSTOM-MIX","freight_company_id":carrier.pk,"freight_number":"F-CUSTOM","shipment_ids":[a_shipment.pk,b_shipment.pk]}, idempotency_key="custom-mixed-batch")
    custom_a = internal_user(world, "http-custom-a", scope=DataScope.ScopeType.CUSTOM, config={"supplier_ids":[world["supplier"].pk]})
    custom_a_client = APIClient(); custom_a_client.force_authenticate(user=custom_a)
    visible_batch_ids = [row["id"] for row in custom_a_client.get("/api/internal/supply-chain/v2/dispatch-batches/").json()["data"]]
    assert mixed_batch.pk not in visible_batch_ids
    supplier_a_shipment_ids = [row["id"] for row in supplier_client.get("/api/external/supplier/supply-chain/v2/shipments/").json()["data"]]
    assert a_shipment.pk in supplier_a_shipment_ids and b_shipment.pk not in supplier_a_shipment_ids
    assert list(LegacyPurchaseOrder.objects.values_list("pk", flat=True)) == legacy_before
    assert list(InventorySnapshot.objects.values_list("pk", flat=True)) == inventory_before


def test_migration_audit_flags_unmapped_legacy_reference_without_writes(world):
    buyer = internal_user(world, "migration-owner")
    legacy = LegacyPurchaseOrder.objects.create(
        tenant=world["tenant"], po_no="LEGACY-UNMAPPED", sku_code="MISSING-SKU",
        supplier_id=987654, quantity=2, unit_price="1.00", created_by=buyer,
    )
    before = (LegacyPurchaseOrder.objects.count(), PurchaseOrder.objects.count(), InventorySnapshot.objects.count())
    output = StringIO()
    call_command("audit_supply_chain_migration", tenant_id=world["tenant"].pk, stdout=output)
    import json
    result = json.loads(output.getvalue())
    assert result["status"] == "blocked"
    assert result["constraint_violations"]["legacy_unresolved_supplier"] == 1
    assert result["constraint_violations"]["legacy_unresolved_sku"] == 1
    assert result["migration_executed"] is False
    assert result["source_rows"] >= 1
    assert (LegacyPurchaseOrder.objects.count(), PurchaseOrder.objects.count(), InventorySnapshot.objects.count()) == before
    assert LegacyPurchaseOrder.objects.get(pk=legacy.pk).po_no == "LEGACY-UNMAPPED"


def test_tenant_and_role_permission_boundaries(world):
    buyer = internal_user(world, "tenant-a")
    order = confirmed_order(world, buyer, key="tenant-order")
    view_only = internal_user(world, "view-only", codes=("supply.v2.view",))
    with pytest.raises(PermissionDenied):
        services.create_purchase_order(view_only, po_payload(world, number="NO-MANAGE"), idempotency_key="no-manage")
    other_tenant = Tenant.objects.create(name="Other tenant", code="sc2-other")
    other_country = CountrySiteMaster.objects.create(tenant=other_tenant, code="us", name="USA", country_code="US")
    other_supplier = SupplierMaster.objects.create(tenant=other_tenant, code="other", name="Other")
    other_user = CustomUser.objects.create_user(username="other-tenant-buyer", tenant=other_tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=other_tenant, code="other-role", name="Other role")
    manage, _ = Permission.objects.get_or_create(code="supply.v2.manage", defaults={"name":"manage","module":"supply","action":"manage","description":"test"})
    view, _ = Permission.objects.get_or_create(code="supply.v2.view", defaults={"name":"view","module":"supply","action":"view","description":"test"})
    role.permissions.add(manage, view)
    UserRole.objects.create(tenant=other_tenant, user=other_user, role=role)
    DataScope.objects.create(tenant=other_tenant, role=role, scope_type=DataScope.ScopeType.ALL)
    with pytest.raises(NotFound):
        services.confirm_purchase_order(other_user, order.pk, expected_version=2, idempotency_key="cross-tenant")
    assert other_country.tenant_id != world["tenant"].pk and other_supplier.tenant_id != world["tenant"].pk


def test_permission_migration_seed_is_present_and_rerunnable_without_losing_grants(world):
    view = Permission.objects.get(code="supply.v2.view")
    manage = Permission.objects.get(code="supply.v2.manage")
    role = Role.objects.create(tenant=world["tenant"], code="migration-grant", name="Existing grant")
    role.permissions.add(view)
    from types import SimpleNamespace
    schema_editor = SimpleNamespace(connection=connection)
    register_v2_permissions(django_apps, schema_editor)
    register_v2_permissions(django_apps, schema_editor)
    view.refresh_from_db()
    manage.refresh_from_db()
    role.refresh_from_db()
    assert role.permissions.filter(pk=view.pk).exists()
    assert Permission.objects.filter(code__in=["supply.v2.view", "supply.v2.manage"]).count() == 2
