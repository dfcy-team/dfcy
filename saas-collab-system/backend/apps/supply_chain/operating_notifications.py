"""Personal procurement reminders configured from supply chain settings."""
from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.accounts.models import CustomUser
from apps.integrations.models import FeishuConfigRule, FeishuConnection, FeishuIdentity
from apps.integrations.feishu_delivery import enqueue_rule, validate_rule_config
from .inbound_notifications import can_manage
from .views import InternalAPI
from .notification_config import require_notify

CODE = 'supply_operating_order_confirmed'


class ConfigInput(serializers.Serializer):
    recipient_user_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=50)
    enabled = serializers.BooleanField()


class ConfigAPI(InternalAPI):
    def get(self, request):
        require_notify(request.user)
        rule = FeishuConfigRule.objects.filter(
            tenant_id=request.user.tenant_id, kind='notification', code=CODE,
        ).first()
        users = CustomUser.objects.filter(
            tenant_id=request.user.tenant_id, is_active=True, user_type='internal',
        ).order_by('username')
        return Response({'data': {
            'enabled': bool(rule and rule.enabled),
            'recipient_user_ids': rule.config.get('recipient_user_ids', []) if rule else [],
            'can_manage': can_manage(request.user),
            'users': [{'id': user.pk, 'name': user.full_name or user.username} for user in users],
        }})

    @transaction.atomic
    def put(self, request):
        if not can_manage(request.user):
            raise PermissionDenied('需要全部数据范围供应链维护及飞书通知管理权限。')
        serializer = ConfigInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data['enabled'] and not data['recipient_user_ids']:
            raise ValidationError('启用前请选择接收采购员。')
        config = {'scene': 'business_alert', 'format': 'card',
                  'recipient_user_ids': sorted(set(data['recipient_user_ids']))}
        validate_rule_config('notification', config, request.user.tenant_id)
        if data['enabled']:
            connection = FeishuConnection.objects.filter(tenant_id=request.user.tenant_id, enabled=True).exclude(app_secret_ref='').first()
            if not connection:
                raise ValidationError('请先配置并启用飞书应用连接。')
            bound = set(FeishuIdentity.objects.filter(
                tenant_id=request.user.tenant_id, user_id__in=config['recipient_user_ids'],
                status='active',
            ).exclude(open_id='').values_list('user_id', flat=True))
            if bound != set(config['recipient_user_ids']):
                raise ValidationError('所选采购员需先绑定飞书账户。')
        FeishuConfigRule.objects.update_or_create(
            tenant_id=request.user.tenant_id, kind='notification', code=CODE,
            defaults={'name': '运营订货确认提醒采购', 'enabled': data['enabled'],
                      'config': config, 'created_by': request.user, 'updated_by': request.user},
        )
        return self.get(request)


def enqueue_confirmed(order):
    rule = FeishuConfigRule.objects.filter(
        tenant_id=order.tenant_id, kind='notification', code=CODE, enabled=True,
    ).first()
    if rule:
        return enqueue_rule(
            rule, key=f'operating-order:{order.pk}:submitted',
            reference_type='operating_order', reference_id=order.pk,
            payload={'operating_order_id': order.pk},
        )
