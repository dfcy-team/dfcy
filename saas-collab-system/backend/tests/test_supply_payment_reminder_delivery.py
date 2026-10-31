from datetime import datetime, timedelta
from unittest.mock import Mock
import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations.models import FeishuConfigRule, FeishuConnection, FeishuDelivery, FeishuIdentity
from apps.integrations.feishu_delivery import execute_delivery, validate_rule_config
from apps.supply_chain import payment_reminder_delivery as delivery
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import PaymentRecord, domain_write
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_payment_reminders import adjust


def setup_rule(world, settings, monkeypatch):
    buyer, api, shipment = pilot(world)
    settings.FEISHU_SYSTEM_BASE_URL = 'https://example.test'
    monkeypatch.setattr(delivery, 'check_user_permission', lambda *a: True)
    monkeypatch.setattr('apps.integrations.feishu_delivery.check_user_permission', lambda *a: True)
    adjust(api, 'shipment', shipment.pk, str(business_date() - timedelta(days=1)))
    FeishuConnection.objects.create(tenant=buyer.tenant, enabled=True, app_id='test', app_secret_ref='fake', created_by=buyer, updated_by=buyer)
    FeishuIdentity.objects.create(tenant=buyer.tenant, user=buyer, open_id='ou_test')
    rule = FeishuConfigRule.objects.create(tenant=buyer.tenant, kind='notification', code='due', name='付款到期', enabled=True,
        config={'scene': 'supply_payment_due', 'hour': 9, 'format': 'card', 'recipient_user_ids': [buyer.pk]}, created_by=buyer, updated_by=buyer)
    return buyer, shipment, rule


@pytest.mark.django_db
def test_daily_reminder_dedup_and_recheck_settled_before_delivery(world, settings, monkeypatch):
    buyer, shipment, rule = setup_rule(world, settings, monkeypatch)
    morning = datetime.combine(business_date(), datetime.min.time()).replace(hour=8)
    delivery.enqueue_due_reminders(morning)
    assert FeishuDelivery.objects.count() == 0
    delivery.enqueue_due_reminders(morning.replace(hour=9))
    delivery.enqueue_due_reminders(morning.replace(hour=10))
    assert FeishuDelivery.objects.count() == 1
    message = delivery.reminder_content(buyer, str(business_date()))
    assert shipment.number in str(message)
    assert f'kind=shipment&id={shipment.pk}' in str(message)
    with domain_write():
        PaymentRecord.objects.create(tenant=buyer.tenant, created_by=buyer, shipment=shipment, amount=20,
            date=business_date(), idempotency_key='paid-before-reminder')
    sender = Mock()
    assert execute_delivery(FeishuDelivery.objects.get().pk, service=sender) == 'skipped'
    sender.send.assert_not_called()


@pytest.mark.django_db
def test_reminder_current_permissions_date_and_real_outbox_content(world, settings, monkeypatch):
    buyer, shipment, rule = setup_rule(world, settings, monkeypatch)
    assert delivery.reminder_content(buyer, str(business_date()-timedelta(days=1))) is None
    delivery.enqueue_due_reminders(datetime.combine(business_date(), datetime.min.time()).replace(hour=9))
    sender = Mock(); sender.send.return_value = 'message-id'
    assert execute_delivery(FeishuDelivery.objects.get().pk, service=sender) == 'success'
    assert shipment.number in str(sender.send.call_args)
    monkeypatch.setattr(delivery, 'check_user_permission', lambda *a: False)
    assert delivery.reminder_content(buyer) is None
    with pytest.raises(ValidationError):
        validate_rule_config('notification', {**rule.config, 'hour': 24}, buyer.tenant_id)
