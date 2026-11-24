from types import SimpleNamespace

import hashlib
import pytest
from django.test import SimpleTestCase

from apps.integrations.feishu_finance_handoff import finance_ready, sync_finance_handoff
from tests.test_supply_chain_v2_foundation import world


class FinanceReadyTests(SimpleTestCase):
    def setUp(self):
        self.instance = SimpleNamespace(finance_snapshot={
            "node_id": "finance-node", "handler_open_id": "handler-open",
        })

    def test_requires_approved_assigned_finance_task(self):
        payload = {
            "status": "APPROVED",
            "task_list": [{"node_id": "finance-node", "open_id": "handler-open", "status": "DONE"}],
        }
        self.assertTrue(finance_ready(self.instance, payload))

    def test_rejects_other_handler_incomplete_or_reverted(self):
        for payload in (
            {"status": "APPROVED", "task_list": [{"node_id": "finance-node", "open_id": "other", "status": "DONE"}]},
            {"status": "APPROVED", "task_list": [{"node_id": "finance-node", "open_id": "handler-open", "status": "PENDING"}]},
            {"status": "APPROVED", "reverted": True, "task_list": [{"node_id": "finance-node", "open_id": "handler-open", "status": "DONE"}]},
        ):
            with self.subTest(payload=payload):
                self.assertFalse(finance_ready(self.instance, payload))


def _make_native_finance(approval, handler, *, business_type, business_id):
    from apps.integrations.models import FeishuIdentity, FeishuApprovalMapping, FeishuApprovalInstance
    from apps.integrations.feishu_native_approval import definition_hash

    FeishuIdentity.objects.update_or_create(tenant=handler.tenant, user=handler, defaults={"open_id": "finance-handler-open", "status": "active"})
    definition = {"status": "ACTIVE", "approval_code": "finance-test"}
    mapping = FeishuApprovalMapping.objects.create(
        tenant=handler.tenant, flow_key="finance-test", business_type=business_type,
        approval_code="finance-test", definition=definition, definition_hash=definition_hash(definition),
        reviewer_id=handler.pk, reviewer_open_id="reviewer", enabled=True,
    )
    approval.business_type = business_type
    approval.business_id = str(business_id)
    approval.save(update_fields=["business_type", "business_id"])
    return FeishuApprovalInstance.objects.create(
        tenant=handler.tenant, approval=approval, mapping=mapping, approval_code="finance-test",
        app_id="synthetic-app", reviewer_open_id="reviewer", payload={}, definition_hash=mapping.definition_hash,
        finance_snapshot={"handler_id": handler.pk, "handler_open_id": "finance-handler-open", "node_id": "finance-node", "date_widget_id": "paid-date", "voucher_widget_id": "voucher"},
    )


def _authoritative(day="2026-11-23", key="opaque-key"):
    return {"status": "APPROVED", "task_list": [{"node_id": "finance-node", "open_id": "finance-handler-open", "status": "DONE"}], "form": [
        {"id": "paid-date", "type": "date", "value": day},
        {"id": "voucher", "type": "attachmentV2", "value": [{"url": "https://files.invalid/path", "name": "receipt.pdf", "source_key": key}]},
    ]}


def _download(key="opaque-key", content=b"%PDF-1.7 test"):
    return [{"source_key": key, "file_name": "receipt.pdf", "media_type": "application/pdf", "byte_size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "content": content}]


def _batch_authoritative():
    body = b"%PDF-1.7 second"
    second = _download("key-two", body)[0]
    second["file_name"] = "receipt-2.pdf"
    return {"status": "APPROVED", "task_list": [{"node_id": "finance-node", "open_id": "finance-handler-open", "status": "APPROVED"}], "form": [
        {"id": "paid-date", "type": "date", "value": "2026-11-23"},
        {"id": "voucher", "type": "attachmentV2", "value": [
            {"url": "https://files.invalid/one", "name": "receipt.pdf", "source_key": "key-one"},
            {"url": "https://files.invalid/two", "name": "receipt-2.pdf", "source_key": "key-two"},
        ]},
    ]}, _download("key-one") + [second]


@pytest.mark.django_db(transaction=True)
def test_single_request_roundtrip_is_idempotent_and_conflicts_require_review(world, monkeypatch):
    from tests.test_supply_payment_request_evidence import _setup_request
    from apps.integrations.feishu_approval_models import FeishuFinanceHandoff
    from apps.supply_chain.payment_request_models import SupplyPaymentRequest, SupplyPaymentRequestVoucher
    from apps.supply_chain.cost_models import PaymentRecord

    buyer, _api, _shipment, _account, row, handler, _reviewer_api = _setup_request(world, monkeypatch)
    approval = __import__("apps.workflows.models", fromlist=["ApprovalRequest"]).ApprovalRequest.objects.get(pk=row["approval_id"])
    instance = _make_native_finance(approval, handler, business_type="supply_payment_request", business_id=row["id"])
    from apps.permissions.models import UserRole, Permission
    role = UserRole.objects.filter(user=handler).select_related("role").first().role
    for code in ("supply.v2.manage", "finance.reconcile"):
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": code.split(".")[0], "action": code.split(".")[-1]})
        role.permissions.add(perm)
    result = sync_finance_handoff(instance, _authoritative(), _download())
    assert result.status == "received" and str(result.actual_payment_date) == "2026-11-23"
    assert SupplyPaymentRequestVoucher.objects.filter(request_id=row["id"]).count() == 1
    replay = sync_finance_handoff(instance, _authoritative(), _download())
    assert replay.status == "received" and SupplyPaymentRequestVoucher.objects.filter(request_id=row["id"]).count() == 1
    changed = sync_finance_handoff(instance, _authoritative(day="2026-11-22"), _download())
    assert changed.status == "needs_review"
    assert FeishuFinanceHandoff.objects.get(instance=instance).status == "needs_review"
    assert SupplyPaymentRequestVoucher.objects.filter(request_id=row["id"]).count() == 1
    assert PaymentRecord.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_invalid_handler_cross_tenant_or_missing_voucher_writes_nothing(world, monkeypatch):
    from tests.test_supply_payment_request_evidence import _setup_request
    from apps.integrations.feishu_finance_handoff import sync_finance_handoff
    from apps.supply_chain.payment_request_models import SupplyPaymentRequestVoucher
    from apps.integrations.feishu_approval_models import FeishuFinanceHandoff
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant

    _buyer, _api, _shipment, _account, row, handler, _reviewer_api = _setup_request(world, monkeypatch)
    approval = __import__("apps.workflows.models", fromlist=["ApprovalRequest"]).ApprovalRequest.objects.get(pk=row["approval_id"])
    instance = _make_native_finance(approval, handler, business_type="supply_payment_request", business_id=row["id"])
    data = _authoritative()
    with pytest.raises(ValueError):
        sync_finance_handoff(instance, data, [])
    foreign_tenant = Tenant.objects.create(name="Foreign finance tenant", code="foreign-finance-test")
    foreign_handler = CustomUser.objects.create_user(username="foreign-finance-handler", tenant=foreign_tenant, user_type="internal")
    instance.finance_snapshot["handler_id"] = foreign_handler.pk
    instance.save(update_fields=["finance_snapshot"])
    with pytest.raises(ValueError):
        sync_finance_handoff(instance, data, _download())
    assert not FeishuFinanceHandoff.objects.filter(instance=instance).exists()
    assert not SupplyPaymentRequestVoucher.objects.filter(request_id=row["id"]).exists()


@pytest.mark.django_db(transaction=True)
def test_batch_saves_all_finance_vouchers_without_posting(world, monkeypatch):
    from tests.test_supply_payment_request_evidence import _setup_request
    from apps.integrations.feishu_approval_models import FeishuFinanceHandoff
    from apps.supply_chain.payment_request_models import SupplyPaymentBatch, SupplyPaymentBatchVoucher
    from apps.supply_chain.cost_models import PayeeAccount, PaymentRecord
    from apps.supply_chain.models import domain_write
    from apps.permissions.models import UserRole, Permission
    from apps.workflows.models import ApprovalRequest

    buyer, _api, _shipment, _account, row, handler, _reviewer_api = _setup_request(world, monkeypatch)
    approval = ApprovalRequest.objects.get(pk=row["approval_id"])
    approval.workflow_snapshot = {**approval.workflow_snapshot, "approval_provider": "feishu"}
    approval.save(update_fields=["workflow_snapshot"])
    account = PayeeAccount.objects.filter(tenant=buyer.tenant).first()
    with domain_write():
        batch = SupplyPaymentBatch.objects.create(
            tenant=buyer.tenant, created_by=buyer, payee_account=account,
            account_snapshot={"nature": "corporate"},
            reason="synthetic batch", status="submitted", approval=approval,
            idempotency_key="finance-test-batch", request_hash="b" * 64,
        )
    instance = _make_native_finance(approval, handler, business_type="supply_payment_batch", business_id=batch.pk)
    role = UserRole.objects.filter(user=handler).select_related("role").first().role
    for code in ("supply.v2.manage", "finance.reconcile"):
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": code.split(".")[0], "action": code.split(".")[-1]})
        role.permissions.add(perm)
    data, files = _batch_authoritative()
    result = sync_finance_handoff(instance, data, files)
    assert result.status == "received"
    assert str(result.actual_payment_date) == "2026-11-23"
    assert SupplyPaymentBatchVoucher.objects.filter(batch=batch).count() == 2
    assert PaymentRecord.objects.count() == 0
    assert FeishuFinanceHandoff.objects.filter(instance=instance, status="received").exists()
    instance.status = 'finished'; instance.provider_status = 'APPROVED'; instance.instance_code = 'synthetic-batch-freshness'
    instance.save(update_fields=['status', 'provider_status', 'instance_code'])
    monkeypatch.setattr('apps.integrations.feishu_native_approval._connection', lambda *a: SimpleNamespace(app_id=instance.app_id))
    truth = {**data, 'instance_code': instance.instance_code, 'approval_code': instance.approval_code,
             'uuid': str(instance.submission_uuid), 'open_id': None}
    monkeypatch.setattr('apps.integrations.feishu_native_approval.FeishuNativeClient', lambda: SimpleNamespace(get_instance=lambda *a: truth))
    byte_values = {f['source_key']: f['content'] for f in files}
    def current_download(item, *, allowed_hosts):
        content = byte_values[item['source_key']]
        return {'source_key': item['source_key'], 'file_name': item['name'], 'content': content,
                'byte_size': len(content), 'sha256': hashlib.sha256(content).hexdigest(), 'media_type': 'application/pdf'}
    monkeypatch.setattr('apps.integrations.feishu_finance_download.download_finance_file', current_download)
    from apps.integrations.feishu_finance_handoff import require_finance_postable
    from rest_framework.exceptions import ValidationError
    post_payload = {'date': '2026-11-23'}
    assert require_finance_postable(handler, approval, post_payload) == truth
    truth['form'] = _batch_authoritative()[0]['form']
    truth['form'][0]['value'] = '2026-11-22'
    with pytest.raises(ValidationError):
        require_finance_postable(handler, approval, post_payload)
    truth['form'] = data['form']
    byte_values['key-one'] = b'%PDF-1.7 changed'
    with pytest.raises(ValidationError):
        require_finance_postable(handler, approval, post_payload)

@pytest.mark.django_db(transaction=True)
def test_finance_return_prefills_date_and_confirmation_copies_formal_voucher(world,monkeypatch):
    from tests.test_supply_payment_request_evidence import _setup_request
    from tests.test_supply_chain_v2_logistics import BASE
    from apps.workflows.models import ApprovalRequest
    from apps.supply_chain.cost_models import PaymentRecord
    from apps.supply_chain.payment_voucher_models import PaymentVoucher
    from apps.supply_chain.payment_request_models import SupplyPaymentRequest
    buyer,api,shipment,account,row,handler,handler_api=_setup_request(world,monkeypatch)
    approval=ApprovalRequest.objects.get(pk=row['approval_id'])
    instance=_make_native_finance(approval,handler,business_type='supply_payment_request',business_id=row['id'])
    approval.workflow_snapshot={**approval.workflow_snapshot,'approval_provider':'feishu'}
    approval.save(update_fields=['workflow_snapshot'])
    instance.status='finished';instance.provider_status='APPROVED';instance.instance_code='formal-copy-synthetic'
    instance.save(update_fields=['status','provider_status','instance_code'])
    data=_authoritative();sync_finance_handoff(instance,data,_download())
    assert PaymentRecord.objects.count()==0
    monkeypatch.setattr('apps.integrations.feishu_native_approval._connection',lambda *a:SimpleNamespace(app_id=instance.app_id))
    truth={**data,'instance_code':instance.instance_code,'approval_code':instance.approval_code,'uuid':str(instance.submission_uuid),'open_id':None}
    synthetic_client = SimpleNamespace(get_instance=lambda *a: truth)
    monkeypatch.setattr('apps.integrations.feishu_native_approval.FeishuNativeClient',lambda: synthetic_client)
    provider_bytes = [_download()[0]['content']]
    def current_download(item, *, allowed_hosts):
        content = provider_bytes[0]
        return {**_download()[0], 'source_key': item['source_key'], 'content': content,
                'byte_size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr('apps.integrations.feishu_finance_download.download_finance_file',current_download)
    source=SupplyPaymentRequest.objects.get(pk=row['id'])
    path=f'{BASE}costs/shipment/{shipment.pk}/payment-requests/{source.pk}/confirm/'
    # The provider form can change before its callback is queued. Posting must
    # compare against the same live response used for native approval validation.
    truth = {**truth, 'form': _authoritative(day='2026-11-22')['form']}
    stale = handler_api.post(path,{'expected_version':source.version},format='json',HTTP_IDEMPOTENCY_KEY='native-finance-stale')
    assert stale.status_code != 200
    assert PaymentRecord.objects.count() == 0
    truth = {**truth, 'form': data['form']}
    provider_bytes[0] = b'%PDF-1.7 changed bytes'
    changed = handler_api.post(path,{'expected_version':source.version},format='json',HTTP_IDEMPOTENCY_KEY='native-finance-bytes-changed')
    assert changed.status_code != 200
    assert PaymentRecord.objects.count() == 0
    provider_bytes[0] = _download()[0]['content']
    response=handler_api.post(path,{'expected_version':source.version},format='json',HTTP_IDEMPOTENCY_KEY='native-finance-confirm')
    assert response.status_code==200,response.data
    payment=PaymentRecord.objects.get(pk=response.data['data']['payment_id'])
    voucher=PaymentVoucher.objects.get(payment=payment)
    assert str(payment.date)=='2026-11-23' and bytes(voucher.content)==_download()[0]['content']
    assert voucher.sha256==_download()[0]['sha256'] and PaymentRecord.objects.count()==1
