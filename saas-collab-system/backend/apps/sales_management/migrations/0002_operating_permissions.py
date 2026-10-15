from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model('permissions', 'Permission')
    rows = [
        ('sales_management.operating_orders.view', '查看运营订货单', 'operating_orders.view', '查看授权国家或本人创建的运营需求', 'action', {}),
        ('sales_management.operating_orders.manage', '维护运营订货单', 'operating_orders.manage', '新货创建、库销比预览、运营核对与提交', 'action', {}),
        ('menu.sales_management.sales_management_operating_orders.view', '运营订货单', 'sales_management_operating_orders.view', '显示销售管理运营订货入口', 'menu',
         {'path': '/sales-management/operating-orders', 'route': '/sales-management/operating-orders', 'parent': '销售管理',
          'resource': 'sales_management_operating_orders', 'action_codes': ['sales_management.operating_orders.view'],
          'source': 'frontend/src/router/menu.js', 'status': 'active'}),
    ]
    for code, name, action, description, kind, metadata in rows:
        Permission.objects.using(schema_editor.connection.alias).update_or_create(code=code, defaults={
            'name': name, 'module': 'sales_management', 'action': action, 'description': description,
            'permission_type': kind, 'metadata': metadata})
    # No implicit grants: platform operators and procurement retain distinct actions.


class Migration(migrations.Migration):
    dependencies = [('sales_management', '0001_initial'), ('permissions', '0001_initial')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
