from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model('permissions', 'Permission')
    Permission.objects.using(schema_editor.connection.alias).update_or_create(
        code='menu.supply.supply_chain_logistics.view',
        defaults={'name': '集货发运与入库', 'module': 'supply', 'action': 'supply_chain_logistics.view',
                  'description': '显示新版集货发运与入库入口', 'permission_type': 'menu',
                  'metadata': {'path': '/supply-chain/logistics', 'route': '/supply-chain/logistics',
                               'resource': 'supply_chain_logistics', 'parent': '供应链协同',
                               'action_codes': ['supply.v2.view'], 'source': 'frontend/src/router/menu.js', 'status': 'active'}})
    # Registration only; do not grant new capabilities to any existing role.


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0008_internal_stock_receipts')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
