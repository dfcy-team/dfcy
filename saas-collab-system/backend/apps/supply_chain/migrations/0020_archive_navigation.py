from django.db import migrations
from django.db.models import Q


def register(apps, schema_editor):
    alias = schema_editor.connection.alias
    Permission = apps.get_model('permissions', 'Permission')
    Role = apps.get_model('permissions', 'Role')
    items = [
        ('supply_archive_suppliers', '供应商档案', '/master-data/suppliers'),
        ('supply_archive_supplier_prices', '供应商价格', '/master-data/supplier-prices'),
        ('supply_archive_freight_companies', '货运公司', '/master-data/freight-companies'),
    ]
    added = []
    for resource, label, path in items:
        permission, _ = Permission.objects.using(alias).update_or_create(
            code=f'menu.supply.{resource}.view',
            defaults={'name': label, 'module': 'supply', 'action': f'{resource}.view',
                      'description': f'显示{label}入口', 'permission_type': 'menu',
                      'metadata': {'path': path, 'route': path, 'resource': path.strip('/').replace('/', '_').replace('-', '_'),
                                   'parent': '基础档案', 'action_codes': ['supply.v2.view'],
                                   'source': 'frontend/src/router/menu.js', 'status': 'active'}},
        )
        added.append(permission)
    # Relocate already-accessible tabs without granting any new action or scope.
    inactive = Permission.objects.using(alias).filter(
        Q(metadata__registry_status__in=['inactive', 'retired']) | Q(metadata__status__in=['inactive', 'retired']))
    cost_menu = Permission.objects.using(alias).filter(code='menu.supply.supply_chain_costs.view').exclude(pk__in=inactive.values('pk')).first()
    if cost_menu:
        added.append(cost_menu)
    source = Permission.objects.using(alias).filter(code__in=[
        'menu.supply.supply_chain_purchase_orders.view', 'supply.v2.view',
    ]).exclude(pk__in=inactive.values('pk'))
    roles = Role.objects.using(alias).filter(permissions__in=source).distinct()
    through = Role.permissions.through
    for role in roles.iterator():
        for permission in added:
            through.objects.using(alias).get_or_create(role_id=role.pk, permission_id=permission.pk)
    Permission.objects.using(alias).filter(code='menu.supply.supply_chain_costs.view').update(
        name='费用与结算', description='显示供应链费用与结算统一入口')


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0019_supplier_shipment_delivery_modes')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
