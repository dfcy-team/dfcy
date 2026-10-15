from django.db import migrations


def register(apps, schema_editor):
    permission = apps.get_model('permissions', 'Permission').objects.using(schema_editor.connection.alias)
    permission.update_or_create(code='supply.v2.notify', defaults={
        'name': '管理供应商外部群自动投递', 'module': 'supply', 'action': 'v2.notify',
        'description': '独立授权配置发送通道、群绑定、验收启用、通知重试及送达证据；不自动授予现有角色。',
        'permission_type': 'action', 'metadata': {}})
    permission.update_or_create(code='menu.supply.supply_chain_notifications.view', defaults={
        'name': '供应商订单通知', 'module': 'supply', 'action': 'supply_chain_notifications.view',
        'description': '显示供应商订单通知通道与处理记录', 'permission_type': 'menu',
        'metadata': {'path': '/supply-chain/notifications', 'route': '/supply-chain/notifications',
                     'resource': 'supply_chain_notifications', 'parent': '供应链协同',
                     'action_codes': ['supply.v2.view'], 'source': 'frontend/src/router/menu.js', 'status': 'active'}})


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0015_notificationthrottle_and_more')]
    # Registration deliberately leaves existing roles unchanged.
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
