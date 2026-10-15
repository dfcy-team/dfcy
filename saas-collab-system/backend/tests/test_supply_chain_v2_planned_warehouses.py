import pytest

from apps.commerce.models import InventorySnapshot
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope, Role, RoleResourcePolicy
from apps.tenants.models import Tenant
from apps.supply_chain.models import BusinessEvent, InboundOrder, InternalStockReceipt
from tests.test_supply_chain_v2_foundation import internal_user, world
from tests.test_supply_chain_v2_logistics import arrive, client, setup, write

BASE = "/api/internal/supply-chain/v2/"


def create_batch(api, shipment, carrier, *, key, planned_id=None):
    body = {"shipment_ids": [shipment.pk], "shipment_versions": [{"id": shipment.pk, "version": shipment.version}],
            "freight_company_id": carrier.pk, "freight_number": f"PLAN-{key}"}
    if planned_id is not None:
        body["planned_warehouse_id"] = planned_id
    response = write(api, "dispatch-batches/", body, key)
    assert response.status_code == 201, response.data
    return response.data["data"]


@pytest.mark.django_db
def test_planned_warehouse_is_default_and_old_batches_accept_explicit_warehouse(world):
    buyer, first, second, carrier, warehouse = setup(world)
    api = client(buyer)
    planned = create_batch(api, first, carrier, key="planned-default", planned_id=warehouse.pk)
    planned = arrive(api, planned)
    response = write(api, f"dispatch-batches/{planned['id']}/inbound/", {
        "expected_version": planned["version"],
    }, "planned-default-inbound")
    assert response.status_code == 200, response.data
    inbound = InboundOrder.objects.get(pk=response.data["data"]["id"])
    assert inbound.warehouse_id == warehouse.pk
    assert response.data["data"]["planned_warehouse_id"] == warehouse.pk
    assert not InternalStockReceipt.objects.exists()
    assert not InventorySnapshot.objects.exists()

    # A legacy batch with no planned warehouse continues to accept an explicit actual warehouse.
    legacy = create_batch(api, second, carrier, key="legacy-no-plan")
    legacy = arrive(api, legacy)
    response = write(api, f"dispatch-batches/{legacy['id']}/inbound/", {
        "expected_version": legacy["version"], "warehouse_id": warehouse.pk,
    }, "legacy-explicit-inbound")
    assert response.status_code == 200, response.data
    assert response.data["data"]["warehouse_id"] == warehouse.pk
    assert response.data["data"]["planned_warehouse_id"] is None
    assert not InternalStockReceipt.objects.exists()
    assert not InventorySnapshot.objects.exists()


@pytest.mark.django_db
def test_plan_changes_and_actual_warehouse_override_require_audited_reasons(world):
    buyer, first, _, carrier, planned = setup(world)
    api = client(buyer)
    replacement = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-replacement",
        name="Replacement US", country_code="US", warehouse_type="owned")
    batch = create_batch(api, first, carrier, key="planned-change", planned_id=planned.pk)

    missing = write(api, f"dispatch-batches/{batch['id']}/", {
        "expected_version": batch["version"], "planned_warehouse_id": replacement.pk,
    }, "plan-change-no-reason", "patch")
    assert missing.status_code == 422
    assert BusinessEvent.objects.filter(aggregate_type="dispatchbatch", aggregate_id=batch["id"],
                                        action="metadata_updated").count() == 0

    changed = write(api, f"dispatch-batches/{batch['id']}/", {
        "expected_version": batch["version"], "planned_warehouse_id": replacement.pk,
        "reason": "客户要求改到新仓",
    }, "plan-change-with-reason", "patch")
    assert changed.status_code == 200, changed.data
    assert changed.data["data"]["planned_warehouse_id"] == replacement.pk
    event = BusinessEvent.objects.get(aggregate_type="dispatchbatch", aggregate_id=batch["id"],
                                      action="metadata_updated")
    assert event.payload["reason"] == "客户要求改到新仓"
    batch = arrive(api, changed.data["data"])

    actual = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-actual",
        name="Actual US", country_code="US", warehouse_type="owned")
    body = {"expected_version": batch["version"], "warehouse_id": actual.pk}
    no_reason = write(api, f"dispatch-batches/{batch['id']}/inbound/", body, "actual-no-reason")
    assert no_reason.status_code == 422
    with_reason = write(api, f"dispatch-batches/{batch['id']}/inbound/", {
        **body, "reason": "实际物流改派至此仓",
    }, "actual-with-reason")
    assert with_reason.status_code == 200, with_reason.data
    assert with_reason.data["data"]["warehouse_id"] == actual.pk
    assert with_reason.data["data"]["planned_warehouse_id"] == replacement.pk
    assert not InternalStockReceipt.objects.exists()
    assert not InventorySnapshot.objects.exists()


@pytest.mark.django_db
def test_planned_warehouse_rejects_inactive_country_and_out_of_scope_references(world):
    buyer, first, _, carrier, _ = setup(world)
    api = client(buyer)
    wrong_country = WarehouseMaster.objects.create(tenant=world["tenant"], code="ca-plan",
        name="CA warehouse", country_code="CA", warehouse_type="owned")
    inactive = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-inactive-plan",
        name="Inactive US", country_code="US", warehouse_type="owned", status="inactive")

    for warehouse, key in ((wrong_country, "wrong-country-plan"), (inactive, "inactive-plan")):
        before = first.version
        response = write(api, "dispatch-batches/", {
            "shipment_ids": [first.pk], "shipment_versions": [{"id": first.pk, "version": before}],
            "freight_company_id": carrier.pk, "freight_number": f"F-{key}",
            "planned_warehouse_id": warehouse.pk,
        }, key)
        assert response.status_code == 422

    tenant_b = Tenant.objects.create(name="warehouse-reference-tenant", code="warehouse-reference-tenant")
    foreign = WarehouseMaster.objects.create(tenant=tenant_b, code="us-foreign-plan",
        name="Foreign US", country_code="US", warehouse_type="owned")
    response = write(api, "dispatch-batches/", {
        "shipment_ids": [first.pk], "shipment_versions": [{"id": first.pk, "version": first.version}],
        "freight_company_id": carrier.pk, "freight_number": "F-foreign-plan",
        "planned_warehouse_id": foreign.pk,
    }, "foreign-plan")
    assert response.status_code == 422

    hidden = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-hidden-plan",
        name="Hidden US", country_code="US", warehouse_type="owned")
    tenant_buyer = internal_user(world, "limited-warehouse", scope=DataScope.ScopeType.CUSTOM,
                                 config={"warehouse_ids": []})
    restricted = client(tenant_buyer)
    options = restricted.get(BASE + "dispatch-options/?country_code=US")
    assert options.status_code == 200
    assert all(row["id"] != hidden.pk for row in options.data["data"]["warehouses"])
    assert not InboundOrder.objects.exists()


@pytest.mark.django_db
def test_inbound_confirmation_rechecks_warehouse_scope_after_draft(world):
    buyer, shipment, _, carrier, warehouse = setup(world)
    api = client(buyer)
    batch = create_batch(api, shipment, carrier, key="scope-recheck")
    batch = arrive(api, batch)
    generated = write(api, f"dispatch-batches/{batch['id']}/inbound/", {
        "expected_version": batch["version"], "warehouse_id": warehouse.pk,
    }, "scope-recheck-generate")
    assert generated.status_code == 200, generated.data
    inbound = generated.data["data"]
    checked = write(api, f"inbound-orders/{inbound['id']}/", {
        "expected_version": inbound["version"], "lines": [
            {"id": line["id"], "received_quantity": line["expected_quantity"], "difference_note": ""}
            for line in inbound["lines"]
        ],
    }, "scope-recheck-check", "patch")
    assert checked.status_code == 200, checked.data

    alternative = WarehouseMaster.objects.create(tenant=world["tenant"], code="us-scope-alternative",
        name="Alternative US", country_code="US", warehouse_type="owned")
    role = Role.objects.get(tenant=world["tenant"], code="role-buyer")
    RoleResourcePolicy.objects.create(tenant=world["tenant"], role=role,
        resource_code="masterdata.warehouses", permission_code="supply.v2.manage",
        scope_type="custom", config={"warehouse_ids": [alternative.pk]})

    confirmed = write(api, f"inbound-orders/{inbound['id']}/confirm/", {
        "expected_version": checked.data["data"]["version"],
    }, "scope-recheck-confirm")
    assert confirmed.status_code == 422, confirmed.data
    assert not InternalStockReceipt.objects.exists()
    assert not InventorySnapshot.objects.exists()
