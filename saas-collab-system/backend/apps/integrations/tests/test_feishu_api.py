from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from unittest.mock import patch

from apps.tenants.models import Tenant
from apps.permissions.models import DataScope, Permission, Role, UserRole

from apps.integrations.models import FeishuConnection


class FeishuApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="FS01", name="Feishu tenant")
        self.user = get_user_model().objects.create_user(
            username="feishu-admin", tenant=self.tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        self.client.force_authenticate(self.user)

    @patch("apps.integrations.feishu_api.get_custody_backend")
    def test_secret_inputs_are_never_returned(self, custody_factory):
        custody_factory.return_value.store_secrets.side_effect = [
            {"credential_id": "cred_app", "token_id": "tok_app"},
            {"credential_id": "cred_verify", "token_id": "tok_verify"},
            {"credential_id": "cred_encrypt", "token_id": "tok_encrypt"},
        ]
        response = self.client.put(
            "/api/internal/integrations/feishu/connection/",
            {
                "app_id": "cli_test", "app_secret": "secret-value",
                "verification_token": "verify-value", "encrypt_key": "encrypt-value",
                "domain": "feishu", "enabled": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        rendered = str(body)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("verify-value", rendered)
        self.assertNotIn("encrypt-value", rendered)
        self.assertTrue(body["data"]["credential_configured"])
        connection = FeishuConnection.objects.get(tenant=self.tenant)
        self.assertTrue(connection.app_secret_ref.startswith("cred_"))
        self.assertNotIn("secret-value", connection.app_secret_ref)
        calls = custody_factory.return_value.store_secrets.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [call.kwargs["metadata"]["value_role"] for call in calls],
            ["app_secret", "verification_token", "encrypt_key"],
        )
        self.assertTrue(all("secret_kind" not in call.kwargs["metadata"] for call in calls))

    def test_six_tab_endpoints_are_available(self):
        for path in ("connection", "identities", "notifications", "reports", "approvals", "operations"):
            response = self.client.get(f"/api/internal/integrations/feishu/{path}/")
            self.assertEqual(response.status_code, 200, path)

    def test_rules_are_tenant_scoped_by_kind(self):
        created = self.client.post(
            "/api/internal/integrations/feishu/reports/",
            {"name": "经营日报", "code": "business_daily", "enabled": True,
             "config": {"schedule": "daily", "delivery": "card"}},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client.get("/api/internal/integrations/feishu/reports/").json()["data"]["items"][0]["code"], "business_daily")
        self.assertEqual(self.client.get("/api/internal/integrations/feishu/approvals/").json()["data"]["items"], [])

    def test_unauthorized_user_is_forbidden_and_fine_grained_write_is_enforced(self):
        limited = get_user_model().objects.create_user(
            username="limited-feishu", tenant=self.tenant,
            user_type="internal", is_active=True,
        )
        self.client.force_authenticate(limited)
        self.assertEqual(self.client.get("/api/internal/integrations/feishu/reports/").status_code, 403)

        role = Role.objects.create(tenant=self.tenant, name="Feishu reports", code="feishu-reports")
        permissions = Permission.objects.filter(code__in=["feishu.view", "feishu.report.manage"])
        self.assertEqual(permissions.count(), 2)
        role.permissions.add(*permissions)
        DataScope.objects.create(tenant=self.tenant, role=role, scope_type="all", config={})
        UserRole.objects.create(tenant=self.tenant, user=limited, role=role)

        report = self.client.post(
            "/api/internal/integrations/feishu/reports/",
            {"name": "Daily", "code": "daily", "config": {}}, format="json",
        )
        self.assertEqual(report.status_code, 201)
        notification = self.client.post(
            "/api/internal/integrations/feishu/notifications/",
            {"name": "Alert", "code": "alert", "config": {}}, format="json",
        )
        self.assertEqual(notification.status_code, 403)
