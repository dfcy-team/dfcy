from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model('permissions', 'Permission')
    Role = apps.get_model('permissions', 'Role')
    permissions = []
    for action, label in [('view', '查看'), ('create', '新建'), ('edit', '更正'), ('register', '确认'),
                          ('void', '作废'), ('import', '导入'), ('export', '导出')]:
        permission, _ = Permission.objects.update_or_create(code='finance.warehouse_fees.' + action,
            defaults={'name': label + '处理费登记', 'module': 'finance', 'action': 'warehouse_fees.' + action,
                      'permission_type': 'action', 'metadata': {},
                      'description': '按国家、仓库和店铺授权登记仓库费用，不发起付款或修改销售订单。'})
        permissions.append(permission)
    menu, _ = Permission.objects.update_or_create(code='menu.finance.finance_warehouse_fees.view', defaults={
        'name': '处理费登记', 'module': 'finance', 'action': 'finance_warehouse_fees.view', 'permission_type': 'menu',
        'description': '显示处理费登记入口', 'metadata': {'path': '/finance/warehouse-fees', 'route': '/finance/warehouse-fees',
        'resource': 'finance_warehouse_fees', 'parent': '财务中心', 'action_codes': ['finance.warehouse_fees.view'],
        'source': 'frontend/src/router/menu.js', 'status': 'active'}})
    permissions.append(menu)
    for role in Role.objects.filter(code__in=['administrator', 'tenant_administrator'], status='active'):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [('finance', '0006_warehouse_fee_registration'), ('permissions', '0038_split_permission_surfaces')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
