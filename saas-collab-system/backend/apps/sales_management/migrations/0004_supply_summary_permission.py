from django.db import migrations


def register(apps, schema_editor):
    apps.get_model('permissions', 'Permission').objects.using(schema_editor.connection.alias).update_or_create(
        code='sales_management.supply_summary.view', defaults={
            'name': '查看国家商品供应数量汇总', 'module': 'sales_management', 'action': 'supply_summary.view',
            'permission_type': 'action', 'description': '按授权国家和库存商品范围查看互斥供应数量，不包含采购单价、供应商信息和单据明细；须独立授权。'})
    # Deliberately no implicit role grants.


class Migration(migrations.Migration):
    dependencies = [('sales_management', '0003_operatingorder_campaign_operatingorder_demand_end_and_more')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
