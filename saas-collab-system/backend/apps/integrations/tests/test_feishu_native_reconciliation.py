from datetime import timedelta
from unittest.mock import Mock
from django.test import TestCase
from django.utils import timezone
from apps.integrations.models import FeishuApprovalInstance, FeishuApprovalEvent, FeishuOperation
from apps.integrations.feishu_approval_callback import reconcile_native_event
from apps.integrations.feishu_native_approval import (enqueue_native_event, process_native_event, submit_instance, reconcile_due_instances)
from apps.supply_chain.models import domain_write
from apps.supply_chain.cost_models import PayeeAccount, PaymentRecord
from apps.supply_chain.payment_request_models import SupplyPaymentRequest
from apps.masterdata.models import SupplierMaster
from apps.workflows.models import WorkflowAuditEvent
from apps.integrations.tests import test_feishu_native_submission as submission_fixture


class NativeReconciliationTests(TestCase):
    def setUp(self):
        submission_fixture.NativeSubmissionTests.setUp(self)
        supplier = SupplierMaster.objects.create(tenant=self.tenant, code='synthetic-supplier', name='Synthetic supplier')
        with domain_write():
            account = PayeeAccount.objects.create(tenant=self.tenant, created_by=self.sender, supplier=supplier, nature='corporate',
                account_name='Synthetic account', account_holder='Synthetic holder', bank_name='Synthetic bank', account_number='00123456')
            row = SupplyPaymentRequest.objects.create(tenant=self.tenant, created_by=self.sender, kind='purchase', source_id=123, amount=self.row.amount,
                currency='PHP', payee_account=account, account_snapshot=self.row.account_snapshot, reason='Synthetic test', status='submitted',
                approval=self.approval, idempotency_key='synthetic-request', request_hash='a'*64)
        self.approval.business_id = str(row.pk); self.approval.save(update_fields=['business_id'])
        self.instance = self.queue()
        self.instance.instance_code = 'synthetic-instance'; self.instance.status = 'submitted'; self.instance.save()
        self.event = {'app_id': 'test-app', 'instance_code': 'synthetic-instance', 'approval_code': 'test-template'}
        self.client_api = Mock()
        self.set_provider('APPROVED')

    queue = submission_fixture.NativeSubmissionTests.queue

    def set_provider(self, status):
        self.client_api.get_instance.return_value = {'instance_code': 'synthetic-instance', 'approval_code': 'test-template',
            'open_id': 'sender-open', 'uuid': str(self.instance.submission_uuid), 'status': status,
            'task_list': [{'user_id': 'unrelated-user-id', 'open_id': 'reviewer-open', 'status': status}]}

    def reconcile(self, event_id='test-event'):
        return reconcile_native_event(self.tenant.pk, event_id, self.event, client=self.client_api)

    def test_approved_updates_approval_audit_once_without_posting_payment(self):
        self.assertEqual(self.reconcile(), 'processed')
        self.approval.refresh_from_db(); self.instance.refresh_from_db()
        self.assertEqual(self.approval.status, 'approved'); self.assertEqual(self.instance.status, 'finished')
        self.assertEqual(self.instance.provider_status, 'APPROVED')
        self.assertEqual(self.reconcile(), 'duplicate')
        self.assertEqual(WorkflowAuditEvent.objects.filter(action='feishu_native_decision').count(), 1)
        self.assertFalse(PaymentRecord.objects.exists())
        self.assertIsNone(SupplyPaymentRequest.objects.get(approval=self.approval).payment_id)

    def test_wrong_template_initiator_reviewer_and_uuid_are_rejected(self):
        for key, value in [('approval_code','wrong-template'), ('open_id','wrong-sender'), ('uuid','wrong-uuid')]:
            self.set_provider('APPROVED'); self.client_api.get_instance.return_value[key] = value
            with self.assertRaises(ValueError): self.reconcile()
        self.set_provider('APPROVED'); self.client_api.get_instance.return_value['task_list'][0]['open_id'] = 'wrong-reviewer'
        with self.assertRaises(ValueError): self.reconcile()
        self.assertFalse(FeishuOperation.objects.filter(reference_id='test-event').exists())

    def test_wrong_tenant_and_stale_business_binding_cannot_write(self):
        other = type(self.tenant).objects.create(code='other-native-tenant', name='Other')
        with self.assertRaises(ValueError): reconcile_native_event(other.pk, 'wrong-tenant', self.event, client=self.client_api)
        self.approval.business_id = '999999'; self.approval.save(update_fields=['business_id'])
        with self.assertRaises(ValueError): self.reconcile()
        self.approval.refresh_from_db(); self.assertEqual(self.approval.status, 'pending')

    def test_pending_cannot_undo_terminal_and_conflict_requires_manual_review(self):
        self.reconcile(); self.set_provider('PENDING'); self.reconcile('late-pending')
        self.instance.refresh_from_db(); self.assertEqual(self.instance.provider_status, 'APPROVED')
        self.assertEqual(self.instance.status, 'finished')
        self.set_provider('REVERTED'); self.reconcile('reverted')
        self.instance.refresh_from_db(); self.assertEqual(self.instance.status, 'manual_review')
        self.approval.refresh_from_db(); self.assertEqual(self.approval.status, 'approved')
        self.assertFalse(PaymentRecord.objects.exists())

    def test_rejected_and_canceled_have_distinct_workflow_states(self):
        self.set_provider('CANCELED'); self.reconcile()
        self.approval.refresh_from_db(); self.assertEqual(self.approval.status, 'withdrawn')
        self.assertIsNone(self.approval.reviewed_by_id)

    def test_rejected_requires_rejecting_designated_reviewer(self):
        self.set_provider('REJECTED'); self.reconcile()
        self.approval.refresh_from_db(); self.assertEqual(self.approval.status, 'rejected')
        self.assertEqual(self.approval.reviewed_by_id, self.reviewer.pk)

    def test_early_callback_then_create_response_preserves_terminal_state(self):
        self.instance.instance_code = None; self.instance.status = 'queued'; self.instance.save()
        client = Mock(); client.get_definition.return_value = self.definition
        def created(*args):
            self.reconcile('early-event')
            return {'instance_code':'synthetic-instance'}
        client.create_instance.side_effect = created
        self.assertEqual(submit_instance(self.instance.pk, client=client)['status'], 'finished')
        self.instance.refresh_from_db(); self.assertEqual(self.instance.status, 'finished')
        self.assertEqual(self.instance.instance_code, 'synthetic-instance')

    def test_authenticated_inbox_persists_before_provider_and_recovers_failure(self):
        self.assertEqual(enqueue_native_event(self.tenant.pk,'durable-event',self.event),'queued')
        self.assertEqual(enqueue_native_event(self.tenant.pk,'durable-event',self.event),'duplicate')
        row = FeishuApprovalEvent.objects.get(event_id='durable-event')
        self.client_api.get_instance.side_effect = TimeoutError
        self.assertEqual(process_native_event(row.pk, client=self.client_api)['status'],'retry')
        self.client_api.get_instance.side_effect = None
        self.assertEqual(process_native_event(row.pk, client=self.client_api)['status'],'done')
        self.approval.refresh_from_db(); self.assertEqual(self.approval.status,'approved')

    def test_periodic_reconciliation_recovers_missing_webhook(self):
        FeishuApprovalInstance.objects.filter(pk=self.instance.pk).update(updated_at=timezone.now()-timedelta(minutes=2))
        results = reconcile_due_instances(client=self.client_api)
        self.assertEqual(results[0]['status'],'processed')
        self.approval.refresh_from_db(); self.assertEqual(self.approval.status,'approved')

    def test_actual_provider_reverted_flag_blocks_confirmation(self):
        from apps.integrations.feishu_native_approval import ensure_native_postable
        from rest_framework.exceptions import ValidationError
        self.reconcile(); self.set_provider('APPROVED')
        self.client_api.get_instance.return_value['reverted'] = True
        with self.assertRaises(ValidationError): ensure_native_postable(self.approval,client=self.client_api)
        self.reconcile('provider-reverted-flag')
        self.instance.refresh_from_db(); self.assertEqual(self.instance.status,'manual_review')

    def test_pending_authenticated_event_and_lookup_failure_block_confirmation(self):
        from apps.integrations.feishu_native_approval import ensure_native_postable
        from rest_framework.exceptions import ValidationError
        self.reconcile()
        enqueue_native_event(self.tenant.pk,'pending-event',self.event)
        with self.assertRaises(ValidationError): ensure_native_postable(self.approval,client=self.client_api)
        FeishuApprovalEvent.objects.filter(event_id='pending-event').update(status='done')
        self.client_api.get_instance.side_effect = TimeoutError
        with self.assertRaises(ValidationError): ensure_native_postable(self.approval,client=self.client_api)
