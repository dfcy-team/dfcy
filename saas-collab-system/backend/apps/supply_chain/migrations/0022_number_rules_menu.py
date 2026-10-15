from django.db import migrations
from django.db.models import Q


def register(apps, schema_editor):
    alias = schema_editor.connection.alias
    Permission = apps.get_model('permissions', 'Permission')
    Role = apps.get_model('permissions', 'Role')
    menu, _ = Permission.objects.using(alias).update_or_create(
        code='menu.supply.supply_chain_settings.view',
        defaults={'name': '供应链设置', 'module': 'supply', 'action': 'supply_chain_settings.view',
                  'description': '显示供应链设置入口', 'permission_type': 'menu',
                  'metadata': {'path': '/supply-chain/settings', 'route': '/supply-chain/settings',
                               'resource': 'supply_chain_settings', 'parent': '供应链协同',
                               'action_codes': ['supply.v2.view'],
                               'source': 'frontend/src/router/menu.js', 'status': 'active'}},
    )
    inactive = Permission.objects.using(alias).filter(
        Q(metadata__registry_status__in=['inactive', 'retired']) | Q(metadata__status__in=['inactive', 'retired']))
    source = Permission.objects.using(alias).filter(code__in=[
        'supply.v2.view', 'menu.supply.supply_chain_purchase_orders.view',
    ]).exclude(pk__in=inactive.values('pk'))
    for role in Role.objects.using(alias).filter(permissions__in=source).distinct().iterator():
        Role.permissions.through.objects.using(alias).get_or_create(role_id=role.pk, permission_id=menu.pk)


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0021_document_number_rules')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
