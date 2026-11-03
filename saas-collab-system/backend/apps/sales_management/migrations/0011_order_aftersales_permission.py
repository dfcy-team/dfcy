from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model('permissions', 'Permission')
    Permission.objects.using(schema_editor.connection.alias).update_or_create(
        code='sales_management.aftersales.manage', defaults={
            'name': '管理订单售后回仓', 'module': 'sales_management', 'action': 'aftersales.manage',
            'description': '配置本地回仓同步、导入仓库实收记录及人工匹配；不执行平台退款、仓库写单或库存调整。',
            'permission_type': 'action', 'metadata': {},
        })
    Permission.objects.using(schema_editor.connection.alias).filter(code='sales_management.returns.view').update(name='查看订单售后')
    Permission.objects.using(schema_editor.connection.alias).filter(code='menu.sales_management.sales_management_returns.view').update(name='订单售后')
    # No role or user receives an implicit new grant.


class Migration(migrations.Migration):
    dependencies = [('sales_management', '0010_order_aftersales'), ('permissions', '0052_history_task_recovery_description')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
