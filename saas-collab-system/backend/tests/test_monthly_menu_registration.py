import pytest
from django.core.management import call_command
from apps.permissions.catalog import runtime_permission_definitions
from apps.permissions.models import Permission,Role
from apps.tenants.models import Tenant

NEW="menu.products.inventory_cost_ledger.view"
OLD="menu.products.products_costs.view"

def test_cost_menus_have_distinct_registered_identity():
 definitions={d["code"]:d for d in runtime_permission_definitions()}
 assert definitions[NEW]["metadata"]["path"]=="/inventory/cost-ledger"
 assert definitions[NEW]["metadata"]["parent"]=="库存管理"
 assert definitions[OLD]["metadata"]["path"]=="/products/costs"
 assert not any(d.get("metadata",{}).get("registry_collision") for d in definitions.values())

@pytest.mark.django_db
def test_sync_persists_new_menu_and_repairs_existing_cost_role():
 call_command("sync_permissions")
 tenant=Tenant.objects.create(name="Monthly menu",code="monthly-menu")
 role=Role.objects.create(tenant=tenant,name="Cost reader",code="cost-reader")
 role.permissions.add(Permission.objects.get(code="products.cost.view"))
 call_command("sync_permissions")
 assert role.permissions.filter(code=NEW).exists()
 assert role.permissions.filter(code=OLD).exists()
 call_command("sync_permissions",check=True)

@pytest.mark.django_db
def test_separate_menu_grants_are_separate_permission_rows():
 call_command("sync_permissions")
 tenant=Tenant.objects.create(name="Separate menu",code="separate-cost-menu")
 role=Role.objects.create(tenant=tenant,name="Monthly only",code="monthly-only")
 role.permissions.add(Permission.objects.get(code=NEW))
 assert role.permissions.filter(code=NEW).exists()
 assert not role.permissions.filter(code=OLD).exists()
