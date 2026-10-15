from django.db import migrations
from django.db.models import Q


def register(apps, schema_editor):
    alias = schema_editor.connection.alias
    Permission = apps.get_model('permissions', 'Permission')
    Role = apps.get_model('permissions', 'Role')
    menu, _ = Permission.objects.using(alias).update_or_create(
        code='menu.supply.supply_archive_warehouses.view',
        defaults={'name': '仓库档案', 'module': 'supply', 'action': 'supply_archive_warehouses.view',
                  'description': '在原仓库档案入口显示供应链仓库业务资料', 'permission_type': 'menu',
                  'metadata': {'path': '/master-data/warehouses', 'route': '/master-data/warehouses',
                               'resource': 'supply_archive_warehouses', 'parent': '基础档案',
                               'action_codes': ['supply.v2.view'], 'source': 'frontend/src/router/menu.js', 'status': 'active'}},
    )
    inactive = Permission.objects.using(alias).filter(
        Q(metadata__registry_status__in=['inactive', 'retired']) | Q(metadata__status__in=['inactive', 'retired']))
    source = Permission.objects.using(alias).filter(code__in=[
        'supply.v2.view', 'menu.supply.supply_chain_purchase_orders.view',
    ]).exclude(pk__in=inactive.values('pk'))
    for role in Role.objects.using(alias).filter(permissions__in=source).distinct().iterator():
        Role.permissions.through.objects.using(alias).get_or_create(role_id=role.pk, permission_id=menu.pk)


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0023_freight_channels_planned_warehouses')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
