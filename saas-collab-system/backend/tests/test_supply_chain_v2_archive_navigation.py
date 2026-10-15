from importlib import import_module

from django.apps import apps

from apps.permissions.models import Permission, Role
from apps.permissions.services import check_user_permission
from tests.test_supply_chain_v2_foundation import world, internal_user

NEW = {'menu.supply.supply_archive_suppliers.view', 'menu.supply.supply_archive_supplier_prices.view',
       'menu.supply.supply_archive_freight_companies.view'}


def test_relocated_archive_menus_preserve_actions_and_scope(world):
    # Transaction tests may flush data migrations before a reused MySQL run.
    # Seed the cost menu owned by the earlier migration explicitly.
    Permission.objects.get_or_create(code='menu.supply.supply_chain_costs.view', defaults={
        'name': '费用与成本', 'module': 'supply', 'action': 'supply_chain_costs.view',
        'permission_type': 'menu', 'metadata': {'status': 'active'}})
    buyer = internal_user(world)
    unrelated = internal_user(world, 'master-reader', codes=('masterdata.view',))
    role = Role.objects.get(code='role-buyer', tenant=world['tenant'])
    before = set(role.permissions.values_list('code', flat=True))
    register = import_module('apps.supply_chain.migrations.0020_archive_navigation').register
    connection = type('SchemaEditor', (), {'connection': type('Connection', (), {'alias': 'default'})()})()
    register(apps, connection)
    assert set(role.permissions.values_list('code', flat=True)) == before | NEW | {'menu.supply.supply_chain_costs.view'}
    assert check_user_permission(buyer, 'supply.v2.view') is True
    assert check_user_permission(buyer, 'masterdata.view') is False
    assert not Role.objects.get(code='role-master-reader').permissions.filter(code__in=NEW).exists()
    for row in Permission.objects.filter(code__in=NEW):
        assert row.permission_type == 'menu'
        assert row.metadata['parent'] == '基础档案'
        assert row.metadata['action_codes'] == ['supply.v2.view']
    assert check_user_permission(unrelated, 'supply.v2.manage') is False


def test_retired_procurement_permission_does_not_reactivate_archive_access(world):
    internal_user(world, codes=('supply.v2.view',))
    Permission.objects.filter(code='supply.v2.view').update(metadata={'status': 'retired'})
    register = import_module('apps.supply_chain.migrations.0020_archive_navigation').register
    connection = type('SchemaEditor', (), {'connection': type('Connection', (), {'alias': 'default'})()})()
    register(apps, connection)
    assert not Role.objects.get(code='role-buyer').permissions.filter(code__in=NEW).exists()


def test_warehouse_menu_reuses_existing_route_without_granting_master_actions(world):
    buyer=internal_user(world)
    unrelated=internal_user(world,'warehouse-master-reader',codes=('masterdata.view',))
    role=Role.objects.get(code='role-buyer',tenant=world['tenant'])
    before=set(role.permissions.values_list('code',flat=True))
    register=import_module('apps.supply_chain.migrations.0024_warehouse_archive_menu').register
    editor=type('SchemaEditor',(),{'connection':type('Connection',(),{'alias':'default'})()})()
    register(apps,editor)
    code='menu.supply.supply_archive_warehouses.view'
    assert set(role.permissions.values_list('code',flat=True))==before|{code}
    menu=Permission.objects.get(code=code)
    assert menu.metadata['path']=='/master-data/warehouses'
    assert menu.metadata['action_codes']==['supply.v2.view']
    assert check_user_permission(buyer,'masterdata.manage') is False
    assert not Role.objects.get(code='role-warehouse-master-reader').permissions.filter(code=code).exists()
    assert check_user_permission(unrelated,'supply.v2.manage') is False
