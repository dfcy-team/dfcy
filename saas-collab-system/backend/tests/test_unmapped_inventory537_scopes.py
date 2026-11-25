"""API-level regressions for the unmapped inventory role branches."""
import pytest
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.masterdata.models import WarehouseMaster
from tests.test_country_inventory_decisions import facts, stock
from tests.test_sales_management import create_scope
from tests.test_supply_chain_v2_logistics import client

URL = "/api/internal/commerce/inventory/category-query/"


def orphan(f, suffix="scope-unmapped", provided=False):
    row = stock(f["tenant"], f["warehouse"], f["sku"], source="RAW-SKU", suffix=suffix,
                provided=provided)
    row.internal_sku = None
    row.save(update_fields=["internal_sku"])
    return row


def set_inventory_roles(f, configs):
    actor = f["actor"]
    permission = Permission.objects.get(code="sales_management.view")
    for user_role in UserRole.objects.filter(user=actor).select_related("role"):
        user_role.role.permissions.remove(permission)
    for n, config in enumerate(configs):
        role = Role.objects.create(tenant=f["tenant"], name=f"unmapped scope {n}",
                                   code=f"unmapped-scope-{actor.pk}-{n}")
        role.permissions.add(permission)
        UserRole.objects.create(tenant=f["tenant"], user=actor, role=role)
        DataScope.objects.create(tenant=f["tenant"], role=role,
                                 scope_type=DataScope.ScopeType.CUSTOM, config=config)


@pytest.mark.django_db
def test_mixed_sku_and_site_only_roles_do_not_expose_unmapped_rows(facts):
    f = facts
    orphan(f)
    set_inventory_roles(f, [
        {"sku_ids": [f["sku"].pk]},
        {"site_ids": [f["country"].pk]},
    ])
    response = client(f["actor"]).get(URL, {"country_id": f["country"].pk, "level": "unmapped"})
    assert response.status_code == 200, response.data
    assert response.data["data"]["results"] == []
    assert response.data["data"]["count"] == 0


@pytest.mark.django_db
def test_unrestricted_product_branch_with_authorized_warehouse_can_see_orphan(facts):
    f = facts
    orphan(f)
    set_inventory_roles(f, [{"warehouse_ids": [f["warehouse"].pk]}])
    response = client(f["actor"]).get(URL, {"country_id": f["country"].pk, "level": "unmapped"})
    assert response.status_code == 200, response.data
    assert [r["source_sku"] for r in response.data["data"]["results"]] == ["RAW-SKU"]


@pytest.mark.django_db
def test_authorized_warehouse_without_unmapped_stock_returns_empty_200(facts):
    f = facts
    empty_warehouse = WarehouseMaster.objects.create(tenant=f["tenant"], code="empty-unmapped-537",
                                                     name="Mapped only warehouse", country_code="PH")
    # The user has an authorized warehouse with inventory, but none of it is
    # unmapped; this distinguishes an empty result from an unauthorized ID.
    stock(f["tenant"], empty_warehouse, f["sku"], source="MAPPED-ONLY", suffix="mapped-only-537")
    set_inventory_roles(f, [{"warehouse_ids": [empty_warehouse.pk]}])
    response = client(f["actor"]).get(URL, {"country_id": f["country"].pk, "level": "unmapped",
                                             "warehouse_id": empty_warehouse.pk})
    assert response.status_code == 200, response.data
    assert response.data["data"]["count"] == 0
    assert response.data["data"]["results"] == []


@pytest.mark.django_db
def test_unmapped_unknown_quantities_are_null_and_internal_run_fields_hidden(facts):
    f = facts
    orphan(f, provided=False)
    response = client(f["actor"]).get(URL, {"country_id": f["country"].pk, "level": "unmapped"})
    assert response.status_code == 200, response.data
    result = response.data["data"]["results"][0]
    assert result["available_qty"] is None and result["on_hand_qty"] is None
    assert "source_run" not in result and not any("failed_count" in key or "status" in key for key in result)
