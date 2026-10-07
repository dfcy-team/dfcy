import hashlib
import base64
import json
import time
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.tenants.models import Tenant
from apps.workflows.models import ApprovalRequest
from apps.integrations.models import FeishuConnection, FeishuConfigRule, FeishuDelivery, FeishuIdentity, FeishuOperation
from apps.integrations.feishu_delivery import enqueue_rule, execute_delivery, notify_approval, dispatch_feishu, FeishuMessageService
from apps.integrations.feishu_api import MENU_CAPABILITIES


@override_settings(FEISHU_SYSTEM_BASE_URL="https://system.example.com")
class FeishuDeliveryTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="FS-DEL", name="Delivery tenant")
        self.owner = get_user_model().objects.create_user(username="del-admin", tenant=self.tenant, user_type="internal", is_superuser=True)
        self.recipient = get_user_model().objects.create_user(username="del-reviewer", tenant=self.tenant, user_type="internal", is_superuser=True)
        self.connection = FeishuConnection.objects.create(tenant=self.tenant, app_id="cli_test", app_secret_ref="cred", enabled=True, created_by=self.owner, updated_by=self.owner)
        self.identity = FeishuIdentity.objects.create(tenant=self.tenant, user=self.recipient, open_id="ou_test")
        self.rule = FeishuConfigRule.objects.create(tenant=self.tenant, name="通知", code="test", kind="notification", enabled=True,
            config={"scene": "business_alert", "recipient_user_ids": [self.recipient.pk], "message": "测试", "format": "card"}, created_by=self.owner, updated_by=self.owner)
        self.client.force_authenticate(self.owner)

    def enqueue(self, key="once"):
        result = enqueue_rule(self.rule, key=key)
        return FeishuDelivery.objects.get(operation_id=result["operation_ids"][0])

    def test_menu_permissions_distinguish_api_access_and_event_subscription(self):
        capabilities = {item["menu"]: item for item in MENU_CAPABILITIES}
        self.assertIn("contact:contact.base:readonly", capabilities["身份映射"]["required_scopes"])
        self.assertIn("contact:user.phone:readonly", capabilities["身份映射"]["optional_scopes"])
        events = capabilities["运行与事件"]
        self.assertEqual(events["required_scopes"], [])
        self.assertIn("im:message.p2p_msg:readonly", events["optional_scopes"])
        self.assertIn("不能替代单聊接收权限", events["note"])
        self.assertNotIn("im:message可覆盖", events["note"])

    def test_outbox_idempotent_and_success_not_replayed(self):
        first, second = self.enqueue(), self.enqueue()
        self.assertEqual(first.pk, second.pk)
        sender = Mock(); sender.send.return_value = "om_test"
        self.assertEqual(execute_delivery(first.pk, service=sender), "success")
        self.assertEqual(execute_delivery(first.pk, service=sender), "success")
        sender.send.assert_called_once()
        self.assertIn("https://system.example.com/", str(sender.send.call_args))

    def test_retry_uses_same_key_and_max_three(self):
        delivery = self.enqueue()
        sender = Mock(); sender.send.side_effect = ValidationError("失败")
        for _ in range(4):
            FeishuDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now())
            execute_delivery(delivery.pk, service=sender)
        self.assertEqual(sender.send.call_count, 3)
        self.assertEqual(len({call.args[-1] for call in sender.send.call_args_list}), 1)

    def test_inflight_lease_prevents_parallel_sender(self):
        delivery = self.enqueue()
        FeishuDelivery.objects.filter(pk=delivery.pk).update(lease_until=timezone.now() + timedelta(minutes=1))
        sender = Mock()
        self.assertEqual(execute_delivery(delivery.pk, service=sender), "processing")
        sender.send.assert_not_called()

    def test_removed_binding_blocked_at_execution(self):
        delivery = self.enqueue(); self.identity.delete()
        sender = Mock()
        self.assertEqual(execute_delivery(delivery.pk, service=sender), "failed")
        sender.send.assert_not_called()

    def test_disabled_user_blocked_at_execution(self):
        delivery = self.enqueue()
        get_user_model().objects.filter(pk=self.recipient.pk).update(is_active=False)
        sender = Mock()
        self.assertEqual(execute_delivery(delivery.pk, service=sender), "failed")
        sender.send.assert_not_called()

    def test_modified_rule_blocked_at_execution(self):
        delivery = self.enqueue()
        self.rule.config["message"] = "改变"; self.rule.save()
        sender = Mock()
        self.assertEqual(execute_delivery(delivery.pk, service=sender), "failed")
        sender.send.assert_not_called()

    def test_unbound_recipient_has_visible_idempotent_skipped_record(self):
        self.identity.delete()
        delivery = self.enqueue(); self.enqueue()
        self.assertEqual(FeishuDelivery.objects.count(), 1)
        self.assertEqual(delivery.operation.status, "skipped")
        self.assertEqual(delivery.operation.error_code, "FEISHU_IDENTITY_UNBOUND")

    def test_cross_tenant_recipient_rejected(self):
        other = Tenant.objects.create(code="OTHER", name="Other")
        user = get_user_model().objects.create_user(username="other-del", tenant=other, user_type="internal")
        self.rule.config["recipient_user_ids"] = [user.pk]
        with self.assertRaises(ValidationError):
            enqueue_rule(self.rule, key="cross")
        self.assertFalse(FeishuOperation.objects.exists())

    def test_manual_run_requires_uuid_and_tenant_rule(self):
        path = f"/api/internal/integrations/feishu/notifications/{self.rule.pk}/run/"
        self.assertEqual(self.client.post(path, {}, format="json").status_code, 400)
        self.assertEqual(self.client.post(path, {"idempotency_key": str(uuid.uuid4())}, format="json").status_code, 202)

    def test_actor_without_feature_permission_cannot_send(self):
        self.recipient.is_superuser = False; self.recipient.save()
        self.client.force_authenticate(self.recipient)
        response = self.client.post(f"/api/internal/integrations/feishu/notifications/{self.rule.pk}/run/", {"idempotency_key": str(uuid.uuid4())}, format="json")
        self.assertEqual(response.status_code, 403)

    def approval(self):
        self.rule.kind = "approval"
        self.rule.config = {"approval_type": "price", "recipient_user_ids": [self.owner.pk, self.recipient.pk]}
        self.rule.save()
        return ApprovalRequest.objects.create(tenant=self.tenant, requested_by=self.owner, approval_type="price", title="价格审批", business_type="price", business_id="1", idempotency_key="approval")

    def test_approval_excludes_applicant_and_respects_current_permissions(self):
        approval = self.approval()
        notify_approval(approval.pk)
        delivery = FeishuDelivery.objects.get()
        self.assertEqual(delivery.user_id, self.recipient.pk)
        self.recipient.is_superuser = False; self.recipient.save()
        sender = Mock()
        self.assertEqual(execute_delivery(delivery.pk, service=sender), "failed")
        sender.send.assert_not_called()

    def test_finished_approval_does_not_send_stale_pending_notice(self):
        approval = self.approval(); notify_approval(approval.pk)
        delivery = FeishuDelivery.objects.get()
        approval.status = "approved"; approval.save()
        sender = Mock()
        self.assertEqual(execute_delivery(delivery.pk, service=sender), "failed")
        sender.send.assert_not_called()

    def test_approval_card_deep_link_and_no_native_approval_call(self):
        approval = self.approval(); notify_approval(approval.pk)
        sender = Mock(); sender.send.return_value = "om_approval"
        self.assertEqual(execute_delivery(FeishuDelivery.objects.get().pk, service=sender), "success")
        self.assertIn(f"/workflow/approvals/{approval.pk}", str(sender.send.call_args))

    def test_persisted_approval_signals_enqueue_pending_and_result_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            approval = self.approval()
        self.assertEqual(FeishuDelivery.objects.get().user_id, self.recipient.pk)
        FeishuIdentity.objects.create(tenant=self.tenant, user=self.owner, open_id="ou_test_owner")
        with self.captureOnCommitCallbacks(execute=True):
            approval.status = "approved"; approval.save()
        result = FeishuDelivery.objects.get(payload__approval_status="approved")
        self.assertEqual(result.user_id, self.owner.pk)
        self.assertEqual(FeishuDelivery.objects.count(), 2)

    def test_scheduled_daily_dispatch_deduplicates(self):
        self.rule.kind = "report"
        self.rule.config = {"report_type": "comprehensive", "recipient_user_ids": [self.recipient.pk], "schedule": "daily", "hour": 0}
        self.rule.save()
        with patch("apps.integrations.feishu_delivery.execute_delivery", return_value="success"):
            dispatch_feishu(); dispatch_feishu()
        self.assertEqual(FeishuDelivery.objects.count(), 1)

    def test_invalid_legacy_rule_does_not_block_other_deliveries(self):
        self.enqueue()
        for i, cfg in enumerate([[], {"hour": "x"}]):
            FeishuConfigRule.objects.create(tenant=self.tenant, name="坏规则", code=f"bad-{i}", kind="report", enabled=True,
                config=cfg, created_by=self.owner, updated_by=self.owner)
        with patch("apps.integrations.feishu_delivery.execute_delivery", return_value="success") as execute:
            dispatch_feishu(); dispatch_feishu()
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(FeishuOperation.objects.filter(error_code="FEISHU_RULE_CONFIG_INVALID").count(), 2)

    def test_message_transport_stable_uuid_no_uncontrolled_http_retry(self):
        http = Mock()
        http.request.side_effect = [Mock(json=lambda: {"code": 0, "tenant_access_token": "token-value"}), Mock(json=lambda: {"code": 0, "data": {"message_id": "om_one"}})]
        custody = Mock(); custody.retrieve_secret.return_value = "secret-value"
        sender = FeishuMessageService(http=http, custody=custody)
        self.assertEqual(sender.send(self.connection, "ou_test", "text", {"text": "test"}, "stable"), "om_one")
        call = http.request.call_args
        self.assertFalse(call.kwargs["retry"])
        self.assertEqual(call.kwargs["json_body"]["uuid"], str(uuid.uuid5(uuid.NAMESPACE_URL, "stable")))

    def test_event_challenge_auth_and_duplicates(self):
        self.connection.verification_token_ref = "verify"; self.connection.save()
        path = f"/api/feishu/events/{self.tenant.pk}/"
        with patch("apps.integrations.feishu_events.get_custody_backend") as custody:
            custody.return_value.retrieve_secret.return_value = "verify-only-test"
            response = self.client.post(path, {"type": "url_verification", "token": "verify-only-test", "challenge": "hello"}, format="json")
            self.assertEqual(response.json(), {"challenge": "hello"})
            self.assertEqual(self.client.post(path, {"type": "url_verification", "token": "wrong", "challenge": "hello"}, format="json").status_code, 403)
            event = {"schema": "2.0", "header": {"token": "verify-only-test", "app_id": "cli_test", "event_id": "e_one", "event_type": "im.message.receive_v1"}, "event": {"secret_message": "must-not-store"}}
            self.assertEqual(self.client.post(path, event, format="json").status_code, 200)
            self.assertTrue(self.client.post(path, event, format="json").json()["duplicate"])
            record = FeishuOperation.objects.get(operation_type="event")
            self.assertNotIn("must-not-store", str(record.masked_detail))
            self.assertFalse(record.masked_detail["business_write"])

    def test_signed_event_expiry_and_invalid_signature(self):
        self.connection.verification_token_ref = "verify"; self.connection.encrypt_key_ref = "encrypt"; self.connection.save()
        event = {"schema": "2.0", "header": {"token": "verify-only-test", "app_id": "cli_test", "event_id": "e_sign", "event_type": "im.message.receive_v1"}}
        raw = json.dumps(event).encode()
        stamp = str(int(time.time())); nonce = "test-nonce"
        signature = hashlib.sha256((stamp + nonce + "encrypt-only-test").encode() + raw).hexdigest()
        path = f"/api/feishu/events/{self.tenant.pk}/"
        with patch("apps.integrations.feishu_events.get_custody_backend") as custody:
            custody.return_value.retrieve_secret.side_effect = lambda key: "verify-only-test" if key == "verify" else "encrypt-only-test"
            headers = {"HTTP_X_LARK_REQUEST_TIMESTAMP": stamp, "HTTP_X_LARK_REQUEST_NONCE": nonce, "HTTP_X_LARK_SIGNATURE": signature}
            self.assertEqual(self.client.post(path, raw, content_type="application/json", **headers).status_code, 200)
            headers["HTTP_X_LARK_SIGNATURE"] = "wrong"
            self.assertEqual(self.client.post(path, raw, content_type="application/json", **headers).status_code, 403)
            headers["HTTP_X_LARK_REQUEST_TIMESTAMP"] = str(int(time.time()) - 600)
            self.assertEqual(self.client.post(path, raw, content_type="application/json", **headers).status_code, 403)

    def test_encrypted_event_verification_and_app_isolation(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        self.connection.verification_token_ref = "verify"; self.connection.encrypt_key_ref = "encrypt"; self.connection.save()
        path = f"/api/feishu/events/{self.tenant.pk}/"
        token_value, encryption_value = "verify-only-test", "encrypt-only-test"
        event = {"schema": "2.0", "header": {"token": token_value, "app_id": "cli_test", "event_id": "e_encrypted", "event_type": "im.message.receive_v1"}}
        def encode_event(payload):
            iv = b"0123456789abcdef"
            padder = PKCS7(128).padder(); padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
            cipher = Cipher(algorithms.AES(hashlib.sha256(encryption_value.encode()).digest()), modes.CBC(iv)).encryptor()
            return json.dumps({"encrypt": base64.b64encode(iv + cipher.update(padded) + cipher.finalize()).decode()}).encode()
        with patch("apps.integrations.feishu_events.get_custody_backend") as custody:
            custody.return_value.retrieve_secret.side_effect = lambda key: token_value if key == "verify" else encryption_value
            for app, expected in [("cli_test", 200), ("cli_other", 403)]:
                event["header"]["app_id"] = app
                raw = encode_event(event); stamp = str(int(time.time())); nonce = "encrypted-test"
                signature = hashlib.sha256((stamp + nonce + encryption_value).encode() + raw).hexdigest()
                response = self.client.post(path, raw, content_type="application/json", HTTP_X_LARK_REQUEST_TIMESTAMP=stamp,
                    HTTP_X_LARK_REQUEST_NONCE=nonce, HTTP_X_LARK_SIGNATURE=signature)
                self.assertEqual(response.status_code, expected)
        self.assertEqual(FeishuOperation.objects.filter(operation_type="event").count(), 1)

    def test_csv_upload_transport_is_bounded_multipart(self):
        http = Mock()
        http.request.side_effect = [Mock(json=lambda: {"code": 0, "tenant_access_token": "test-token-value"}), Mock(json=lambda: {"code": 0, "data": {"file_key": "file_test"}})]
        custody = Mock(); custody.retrieve_secret.return_value = "test-secret-value"
        sender = FeishuMessageService(http=http, custody=custody)
        self.assertEqual(sender.upload_csv(self.connection, b"dataset,value\nsales,1\n"), "file_test")
        request = http.request.call_args
        self.assertFalse(request.kwargs["retry"])
        self.assertIn(b'name="file_type"\r\n\r\nstream', request.kwargs["raw_body"])
        self.assertIn(b"sales,1", request.kwargs["raw_body"])
        self.assertIn("multipart/form-data", request.kwargs["headers"]["Content-Type"])
