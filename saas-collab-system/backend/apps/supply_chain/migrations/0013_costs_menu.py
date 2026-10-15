from django.db import migrations


def register(apps, schema_editor):
    apps.get_model('permissions', 'Permission').objects.using(schema_editor.connection.alias).update_or_create(
        code='menu.supply.supply_chain_costs.view',
        defaults={'name': '费用与成本', 'module': 'supply', 'action': 'supply_chain_costs.view',
                  'description': '显示新版供应链费用与成本入口', 'permission_type': 'menu',
                  'metadata': {'path': '/supply-chain/costs', 'route': '/supply-chain/costs',
                               'resource': 'supply_chain_costs', 'parent': '供应链协同',
                               'action_codes': ['supply.v2.view'], 'source': 'frontend/src/router/menu.js',
                               'status': 'active'}})


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0012_costversion_costentry_costadjustment_feerecord_and_more')]
    # Register the entry without granting it to existing roles.
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
