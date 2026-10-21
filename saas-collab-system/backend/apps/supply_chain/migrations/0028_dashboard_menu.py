from django.db import migrations


def register(apps, schema_editor):
    apps.get_model('permissions','Permission').objects.using(schema_editor.connection.alias).update_or_create(
        code='menu.supply.supply_chain_dashboard.view', defaults={
            'name':'供应链驾驶舱', 'module':'supply', 'action':'supply_chain_dashboard.view',
            'permission_type':'menu', 'description':'查看供应链国家进度与费用驾驶舱',
            'metadata':{'path':'/supply-chain/dashboard','route':'/supply-chain/dashboard',
                'resource':'supply_chain_dashboard','parent':'供应链协同','action_codes':['supply.v2.view'],
                'source':'frontend/src/router/menu.js','status':'active'}})


class Migration(migrations.Migration):
    dependencies=[('supply_chain','0027_paymentvoucher')]
    operations=[migrations.RunPython(register,migrations.RunPython.noop)]
