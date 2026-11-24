import hashlib
import json
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.tenants.models import Tenant
from apps.integrations.models import FeishuConnection


class NativeApprovalCallbackTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="NATIVE-CB", name="Callback")
        user = get_user_model().objects.create_user(username="native-callback", tenant=self.tenant)
        self.connection = FeishuConnection.objects.create(tenant=self.tenant, app_id="cli_native",
            verification_token_ref="token-ref", encrypt_key_ref="encrypt-ref", enabled=True,
            created_by=user, updated_by=user)
        self.url = reverse("feishu-event-callback", args=[self.tenant.pk])

    def post_event(self, *, token="test-verify", app_id="cli_native", event_id="evt-1", status="APPROVED"):
        stamp, nonce, key = str(int(time.time())), "nonce", "encryption-key"
        raw = json.dumps({"type": "event_callback", "uuid": event_id, "token": token, "event": {
            "app_id": app_id, "tenant_key": "tenant", "type": "approval_instance",
            "approval_code": "approval-code", "instance_code": "instance-code", "status": status,
        }}).encode()
        signature = hashlib.sha256((stamp + nonce + key).encode() + raw).hexdigest()
        with patch("apps.integrations.feishu_events.get_custody_backend") as custody:
            custody.return_value.retrieve_secret.side_effect = lambda ref: {"token-ref": "test-verify", "encrypt-ref": key}[ref]
            return self.client.post(self.url, raw, content_type="application/json", HTTP_X_LARK_REQUEST_TIMESTAMP=stamp,
                HTTP_X_LARK_REQUEST_NONCE=nonce, HTTP_X_LARK_SIGNATURE=signature)

    @patch("apps.integrations.feishu_events.enqueue_native_event", return_value="processed")
    def test_native_v1_event_uses_top_level_uuid_and_authorized_signature(self, reconcile):
        response = self.post_event()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reconcile.call_args.args[1], "evt-1")

    @patch("apps.integrations.feishu_events.enqueue_native_event")
    def test_bad_token_or_app_id_is_rejected(self, reconcile):
        self.assertEqual(self.post_event(token="test-wrong").status_code, 403)
        self.assertEqual(self.post_event(app_id="other-app").status_code, 403)
        reconcile.assert_not_called()

    @patch("apps.integrations.feishu_events.enqueue_native_event", return_value="processed")
    def test_schema2_message_callback_remains_supported(self, reconcile):
        raw = json.dumps({"schema": "2.0", "header": {"token": "test-verify", "app_id": "cli_native",
            "event_id": "message-event", "event_type": "im.message.receive_v1"}, "event": {}}).encode()
        with patch("apps.integrations.feishu_events.get_custody_backend") as custody:
            custody.return_value.retrieve_secret.side_effect = lambda ref: {"token-ref": "test-verify", "encrypt-ref": "encryption-key"}[ref]
            stamp, nonce, key = str(int(time.time())), "nonce", "encryption-key"
            signature = hashlib.sha256((stamp + nonce + key).encode() + raw).hexdigest()
            response = self.client.post(self.url, raw, content_type="application/json", HTTP_X_LARK_REQUEST_TIMESTAMP=stamp,
                HTTP_X_LARK_REQUEST_NONCE=nonce, HTTP_X_LARK_SIGNATURE=signature)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)
