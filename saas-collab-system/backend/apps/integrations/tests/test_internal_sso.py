import base64
import hashlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.integrations.models import InternalAPIClient, InternalSSOAuthorizationCode
from apps.tenants.models import Tenant


class InternalSSOTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(code="SSO1", name="SSO tenant")
        self.user = get_user_model().objects.create_user(
            username="sso-user", password="test-password", tenant=self.tenant,
            user_type="internal", is_active=True, full_name="SSO User",
        )
        self.secret = "machine-secret"
        self.callback = "https://caller.example.test/login/callback"
        self.machine = InternalAPIClient.objects.create(
            tenant=self.tenant, name="Caller", caller_type="internal_system",
            client_id="intapi_sso_test", secret_hash=make_password(self.secret),
            secret_prefix="machine-", secret_fingerprint="test", resources={},
            allowed_cidrs=["127.0.0.1/32"], allow_sso_login=True,
            sso_redirect_uris=[self.callback], status="active", approval_status="approved",
            created_by=self.user, updated_by=self.user,
        )
        self.verifier = "a" * 43
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        self.auth_request = {
            "client_id": self.machine.client_id, "redirect_uri": self.callback,
            "state": "safe_state_value_123", "code_challenge": self.challenge,
        }

    def authorize(self):
        self.client.force_authenticate(self.user)
        return self.client.post("/api/internal/integrations/sso/authorize/", self.auth_request, format="json")

    def exchange(self, code, **overrides):
        self.client.force_authenticate(user=None)
        basic = base64.b64encode(f"{self.machine.client_id}:{self.secret}".encode()).decode()
        payload = {"code": code, "redirect_uri": self.callback, "code_verifier": self.verifier}
        payload.update(overrides)
        return self.client.post("/api/internal-readonly/v1/auth/token/", payload, format="json", HTTP_AUTHORIZATION=f"Basic {basic}")

    def test_one_time_exchange_returns_identity_only(self):
        response = self.authorize()
        self.assertEqual(response.status_code, 200, response.content)
        from urllib.parse import parse_qs, urlsplit
        url = response.json()["data"]["redirect_url"]
        self.assertEqual(urlsplit(url).scheme, "https")
        self.assertEqual(parse_qs(urlsplit(url).query)["state"], [self.auth_request["state"]])
        code = parse_qs(urlsplit(url).query)["code"][0]
        self.assertFalse(InternalSSOAuthorizationCode.objects.filter(code_hash=code).exists())
        result = self.exchange(code)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(set(result.json()["data"]), {"user_id", "username", "full_name", "tenant_id"})
        self.assertNotIn("password", str(result.content).lower())
        self.assertEqual(self.exchange(code).status_code, 400)

    def test_callback_mismatch_and_disabled_client_are_denied(self):
        self.auth_request["redirect_uri"] = "https://evil.example.test/callback"
        self.assertEqual(self.authorize().status_code, 403)
        self.auth_request["redirect_uri"] = self.callback
        self.machine.allow_sso_login = False
        self.machine.save(update_fields=["allow_sso_login"])
        self.assertEqual(self.authorize().status_code, 403)

    def test_wrong_pkce_and_expired_code_cannot_exchange(self):
        from urllib.parse import parse_qs, urlsplit
        code = parse_qs(urlsplit(self.authorize().json()["data"]["redirect_url"]).query)["code"][0]
        self.assertEqual(self.exchange(code, code_verifier="b" * 43).status_code, 400)
        InternalSSOAuthorizationCode.objects.filter(code_hash=hashlib.sha256(code.encode()).hexdigest()).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(self.exchange(code).status_code, 400)

    def test_sso_only_client_cannot_read_data_blocks(self):
        basic = base64.b64encode(f"{self.machine.client_id}:{self.secret}".encode()).decode()
        response = self.client.get("/api/internal-readonly/v1/products/", HTTP_AUTHORIZATION=f"Basic {basic}")
        self.assertEqual(response.status_code, 403)

    def test_other_tenant_and_external_user_cannot_authorize(self):
        other = Tenant.objects.create(code="SSO2", name="Other")
        self.user.tenant = other
        self.user.save(update_fields=["tenant"])
        self.assertEqual(self.authorize().status_code, 403)
        self.user.tenant = self.tenant
        self.user.user_type = "external"
        self.user.save(update_fields=["tenant", "user_type"])
        self.assertEqual(self.authorize().status_code, 403)

    def test_unapproved_client_and_removed_callback_cannot_exchange(self):
        from urllib.parse import parse_qs, urlsplit
        code = parse_qs(urlsplit(self.authorize().json()["data"]["redirect_url"]).query)["code"][0]
        self.machine.sso_redirect_uris = []
        self.machine.save(update_fields=["sso_redirect_uris"])
        self.assertEqual(self.exchange(code).status_code, 400)
        self.machine.sso_redirect_uris = [self.callback]
        self.machine.approval_status = "pending"
        self.machine.save(update_fields=["sso_redirect_uris", "approval_status"])
        self.assertEqual(self.authorize().status_code, 403)
        self.assertEqual(self.exchange(code).status_code, 401)

    def test_authorize_is_rate_limited_per_user(self):
        cache.clear()
        for _ in range(20):
            self.assertEqual(self.authorize().status_code, 200)
        self.assertEqual(self.authorize().status_code, 429)
