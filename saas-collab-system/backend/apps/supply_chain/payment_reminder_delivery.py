"""Daily payment reminders through the existing durable Feishu outbox.

No financial snapshot is stored in messages: permission and balance are checked
again immediately before delivery. Unknown balances/dates are never guessed.
"""
from django.db import transaction
from apps.integrations.models import FeishuConfigRule, FeishuOperation
from apps.integrations.feishu_delivery import active_user, card, enqueue_rule, system_url, validate_rule_config
from apps.permissions.services import check_user_permission
from apps.tenants.models import Tenant
from .dates import business_date
from .payment_reminders import KINDS, reminder_query
from .permissions import VIEW

LABELS = {'shipment': '供应商货款', 'domestic_freight': '国内运费', 'batch': '批次货运费', 'inbound': '清关费'}


def reminder_content(user, scheduled_date=None):
    if not active_user(user) or not check_user_permission(user, VIEW):
        return None
    if scheduled_date and scheduled_date != business_date().isoformat():
        return None  # Do not deliver yesterday's pending reminder today.
    lines, links = [], []
    for kind in KINDS:
        rows = list(reminder_query(user, kind).filter(
            terms_status__in=['overdue', 'due_soon'], remaining_amount__gt=0
        ).order_by('terms_due', 'pk')[:6])
        if not rows:
            continue
        lines.append(LABELS[kind] + ('（仅列最早到期5张）' if len(rows) > 5 else ''))
        for row in rows[:5]:
            status = '已逾期' if row.terms_status == 'overdue' else '即将到期'
            lines.append(f'{row.number} · {row._party_name} · {status} {row.terms_due} · 剩余 {row.remaining_amount:.2f}')
            if len(links) < 5:
                links.append((row.number, f'/supply-chain/costs?kind={kind}&id={row.pk}'))
    if not lines:
        return None
    content = card('供应链付款到期提醒', '\n'.join(lines) + '\n金额按当前权限及有效付款计算；请进入系统核对并办理。', '/supply-chain/costs')
    content['elements'].append({'tag': 'action', 'actions': [
        {'tag': 'button', 'text': {'tag': 'plain_text', 'content': number}, 'url': system_url(path)} for number, path in links
    ]})
    return 'interactive', content


def enqueue_due_reminders(local):
    rules = FeishuConfigRule.objects.filter(kind='notification', enabled=True).select_related('updated_by')
    for rule in rules.iterator(chunk_size=100):
        if not isinstance(rule.config, dict) or rule.config.get('scene') != 'supply_payment_due':
            continue
        try:
            validate_rule_config(rule.kind, rule.config, rule.tenant_id)
            if local.hour < rule.config.get('hour', 9):
                continue
            if not active_user(rule.updated_by) or not check_user_permission(rule.updated_by, 'feishu.notification.manage'):
                continue
            # Tenant lock also serializes concurrent schedulers. Outbox key is
            # stable per rule/day/recipient, including skipped unbound users.
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=rule.tenant_id)
                enqueue_rule(rule, key=f'payment-due:{local.date().isoformat()}',
                    reference_type='supply_payment_due', reference_id=rule.pk,
                    payload={'reminder_date': local.date().isoformat()})
        except Exception:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=rule.tenant_id)
                FeishuOperation.objects.get_or_create(tenant_id=rule.tenant_id, operation_type='notification',
                    reference_type='payment_reminder_config', reference_id=f'{rule.pk}:{local.date().isoformat()}',
                    defaults={'status': 'failed', 'error_code': 'PAYMENT_REMINDER_CONFIG_INVALID',
                        'masked_detail': {'rule_id': rule.pk, 'error_message': '付款提醒规则或飞书连接未就绪，请检查配置。'}})
