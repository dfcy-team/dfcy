import copy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.workflows.models import ApprovalRequest
from apps.integrations.models import FeishuConnection, FeishuIdentity, FeishuApprovalMapping, FeishuApprovalInstance
from apps.integrations.feishu_native_approval import definition_hash, queue_payment_approval, submit_instance, ensure_native_postable
from apps.integrations.tests.test_feishu_payment_form import definition


class NativeSubmissionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Native test', code='native-submission-test')
        self.sender = CustomUser.objects.create_user(username='native-sender', tenant=self.tenant, user_type='internal')
        self.reviewer = CustomUser.objects.create_user(username='native-reviewer', tenant=self.tenant, user_type='internal')
        self.connection = FeishuConnection.objects.create(tenant=self.tenant, app_id='test-app', enabled=True,
            app_secret_ref='synthetic-ref', verification_token_ref='synthetic-ref', encrypt_key_ref='synthetic-ref', created_by=self.sender, updated_by=self.sender)
        for user, oid in [(self.sender, 'sender-open'), (self.reviewer, 'reviewer-open')]:
            FeishuIdentity.objects.create(tenant=self.tenant, user=user, open_id=oid)
        self.definition = {**definition(), 'status': 'ACTIVE', 'approval_code': 'test-template', 'node_list': []}
        self.mapping = FeishuApprovalMapping.objects.create(tenant=self.tenant, flow_key='test-flow', business_type='supply_payment_request',
            approval_code='test-template', definition=self.definition, definition_hash=definition_hash(self.definition), reviewer_id=self.reviewer.pk,
            reviewer_open_id='reviewer-open', enabled=True, fixed_assignees_verified=True, subscription_verified=True)
        self.approval = ApprovalRequest.objects.create(tenant=self.tenant, requested_by=self.sender, designated_reviewer=self.reviewer,
            business_type='supply_payment_request', business_id='123', approval_type='finance', title='Synthetic test', idempotency_key='native-approval',
            workflow_snapshot={'flow_key': 'test-flow'})
        self.row = SimpleNamespace(tenant_id=self.tenant.pk, approval_id=self.approval.pk, amount=Decimal('123.4500'), currency='PHP', reason='Synthetic test',
            account_snapshot={'account_holder': 'Synthetic recipient', 'bank_name': 'Synthetic bank', 'account_number': '00123456'})
        self.form_input = {'payment_type': '供应商货款', 'payment_method': '银行卡', 'payment_date': '2026-11-24'}

    def queue(self):
        return queue_payment_approval(self.approval, self.row, form_input=self.form_input)

    def test_unmapped_preserves_internal_flow(self):
        self.mapping.enabled = False; self.mapping.save()
        self.assertIsNone(self.queue())
        self.assertFalse(FeishuApprovalInstance.objects.exists())

    def test_php_original_amount_identity_and_idempotency(self):
        instance = self.queue()
        self.assertEqual(instance.payload['open_id'], 'sender-open')
        amount = next(v for v in instance.payload['form'] if v['type'] == 'amount')
        self.assertEqual(amount['value'], 123.45)
        self.assertEqual(amount['currency'], 'PHP')
        self.assertEqual(self.queue().pk, instance.pk)
        self.assertEqual(FeishuApprovalInstance.objects.count(), 1)
        self.assertEqual(self.approval.workflow_snapshot['approval_provider'], 'feishu')
        self.assertEqual(instance.app_id, 'test-app')
        self.assertEqual(instance.reviewer_open_id, 'reviewer-open')

    def test_missing_inputs_and_reviewer_mismatch_fail_closed(self):
        with self.assertRaises(ValidationError): queue_payment_approval(self.approval, self.row)
        self.mapping.reviewer_id = self.sender.pk; self.mapping.save()
        with self.assertRaises(ValidationError): self.queue()
        self.assertFalse(FeishuApprovalInstance.objects.exists())

    def test_missing_callback_configuration_blocks_submission(self):
        self.connection.encrypt_key_ref = ''; self.connection.save()
        with self.assertRaises(ValidationError): self.queue()
        self.assertFalse(FeishuApprovalInstance.objects.exists())

    def test_changed_replay_content_rejected(self):
        self.queue(); self.row.amount = Decimal('124')
        with self.assertRaises(ValidationError): self.queue()

    def test_business_request_only_persists_outbox_and_never_calls_broker(self):
        with patch('apps.integrations.tasks.submit_feishu_native_approval.delay') as dispatch:
            instance = self.queue()
            self.assertEqual(instance.status, 'queued')
            dispatch.assert_not_called()

    def test_success_and_no_second_instance(self):
        instance = self.queue(); client = Mock()
        client.get_definition.return_value = self.definition
        client.create_instance.return_value = {'instance_code': 'synthetic-instance'}
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'submitted')
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'submitted')
        client.create_instance.assert_called_once()
        self.assertEqual(client.create_instance.call_args.args[1]['uuid'], str(instance.submission_uuid))

    def test_network_timeout_reuses_stable_uuid(self):
        instance = self.queue(); client = Mock()
        client.get_definition.return_value = self.definition
        client.create_instance.side_effect = TimeoutError
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'retry')
        first = copy.deepcopy(client.create_instance.call_args.args[1])
        client.create_instance.side_effect = None; client.create_instance.return_value = {'instance_code': 'synthetic-instance'}
        from apps.integrations.feishu_native_client import FeishuNativeAPIError
        client.get_instance.side_effect = FeishuNativeAPIError('not found',1390003)
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'submitted')
        self.assertEqual(client.create_instance.call_args.args[1], first)

    def test_changed_definition_or_app_does_not_create(self):
        instance = self.queue(); client = Mock()
        client.get_definition.return_value = {**self.definition, 'status': 'DELETED'}
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'retry')
        client.create_instance.assert_not_called()
        self.connection.app_id = 'other-app'; self.connection.save()
        client.get_definition.reset_mock()
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'retry')
        client.get_definition.assert_not_called()

    def test_active_lease_and_disabled_mapping_do_not_send(self):
        from datetime import timedelta
        instance = self.queue(); instance.lease_until = timezone.now() + timedelta(minutes=2); instance.save()
        client = Mock()
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'busy')
        client.get_definition.assert_not_called()
        instance.lease_until = None; instance.save(); self.mapping.enabled = False; self.mapping.save()
        self.assertEqual(submit_instance(instance.pk, client=client)['status'], 'blocked')
        client.get_definition.assert_not_called()

    def test_confirmation_requires_verified_approved_terminal(self):
        instance = self.queue()
        with self.assertRaises(ValidationError): ensure_native_postable(self.approval)
        instance.status = 'finished'; instance.provider_status = 'APPROVED'; instance.instance_code = 'synthetic-instance'; instance.save()
        client = Mock(); client.get_instance.return_value = {'status':'APPROVED','instance_code':'synthetic-instance','approval_code':'test-template','uuid':str(instance.submission_uuid),'open_id':'sender-open'}
        ensure_native_postable(self.approval, client=client)
        instance.status = 'manual_review'; instance.save()
        with self.assertRaises(ValidationError): ensure_native_postable(self.approval)

    def test_lost_creation_response_is_recovered_by_submission_uuid(self):
        instance = self.queue(); instance.attempts = 1; instance.status = 'retry'; instance.save()
        client = Mock(); client.get_definition.return_value = self.definition
        client.get_instance.return_value = {'instance_code':'recovered-instance','approval_code':'test-template',
            'uuid':str(instance.submission_uuid),'open_id':'sender-open'}
        self.assertEqual(submit_instance(instance.pk,client=client)['status'],'submitted')
        client.get_instance.assert_called_once_with(self.connection,str(instance.submission_uuid))
        client.create_instance.assert_not_called()
        instance.refresh_from_db(); self.assertEqual(instance.instance_code,'recovered-instance')
