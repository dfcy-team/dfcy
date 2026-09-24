from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase
from unittest.mock import Mock, patch

from apps.tenants.models import Tenant
from apps.permissions.models import DataScope, Permission, Role, UserRole

from apps.integrations.models import FeishuConnection, FeishuIdentity
from apps.integrations.feishu_identity_service import FeishuIdentityService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


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

    def test_identity_list_contains_unbound_tenant_users_and_masks_contacts(self):
        colleague = get_user_model().objects.create_user(
            username="operator", full_name="张三", email="zhangsan@example.com",
            phone="13800138000", tenant=self.tenant, user_type="internal", is_active=True,
        )
        response = self.client.get("/api/internal/integrations/feishu/identities/")
        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json()["data"]["items"] if row["system_user_id"] == colleague.id)
        self.assertEqual(item["full_name"], "张三")
        self.assertIsNone(item["mapping"])
        self.assertEqual(item["contacts"]["email"], "z*******@example.com")
        self.assertEqual(item["contacts"]["phone"], "*******8000")

    def test_legacy_identity_write_paths_cannot_bypass_candidate_verification(self):
        colleague = get_user_model().objects.create_user(
            username="operator-legacy", tenant=self.tenant, user_type="internal", is_active=True,
        )
        collection = self.client.post(
            "/api/internal/integrations/feishu/identities/",
            {"system_user_id": colleague.id, "open_id": "ou_injected"}, format="json",
        )
        self.assertEqual(collection.status_code, 405)
        mapping = FeishuIdentity.objects.create(
            tenant=self.tenant, user=colleague, open_id="ou_existing",
        )
        detail = self.client.patch(
            f"/api/internal/integrations/feishu/identities/{mapping.id}/",
            {"open_id": "ou_injected"}, format="json",
        )
        self.assertEqual(detail.status_code, 405)
        mapping.refresh_from_db()
        self.assertEqual(mapping.open_id, "ou_existing")

    @patch("apps.integrations.feishu_api.FeishuIdentityService")
    def test_candidate_lookup_is_scoped_to_system_user(self, service_class):
        colleague = get_user_model().objects.create_user(
            username="operator-candidate", email="operator@example.com", tenant=self.tenant,
            user_type="internal", is_active=True,
        )
        FeishuConnection.objects.create(
            tenant=self.tenant, app_id="cli_test", app_secret_ref="cred_test", enabled=True,
            created_by=self.user, updated_by=self.user,
        )
        service_class.return_value.find_candidates.return_value = [{
            "open_id": "ou_candidate", "name": "候选人", "email": "o*******@example.com",
            "phone": "", "user_id": "", "union_id": "", "department_ids": [],
        }]
        response = self.client.post(
            f"/api/internal/integrations/feishu/identities/system-users/{colleague.id}/candidates/", {}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["candidates"][0]["open_id"], "ou_candidate")

    @patch("apps.integrations.feishu_api.FeishuIdentityService")
    def test_confirm_binding_creates_then_updates_and_is_tenant_scoped(self, service_class):
        colleague = get_user_model().objects.create_user(
            username="operator-bind", tenant=self.tenant, user_type="internal", is_active=True,
        )
        service_class.return_value.find_candidates.side_effect = [
            [{"open_id": "ou_first", "user_id": "u1", "union_id": "", "department_ids": []}],
            [{"open_id": "ou_second", "user_id": "", "union_id": "on_2", "department_ids": []}],
        ]
        path = f"/api/internal/integrations/feishu/identities/system-users/{colleague.id}/binding/"
        created = self.client.put(path, {"open_id": "ou_first", "user_id": "u1"}, format="json")
        self.assertEqual(created.status_code, 200, created.content)
        updated = self.client.put(path, {"open_id": "ou_second", "union_id": "on_2"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(FeishuIdentity.objects.get(tenant=self.tenant, user=colleague).open_id, "ou_second")
        self.assertEqual(FeishuIdentity.objects.filter(tenant=self.tenant, user=colleague).count(), 1)

        other_tenant = Tenant.objects.create(code="FS02", name="Other tenant")
        other_user = get_user_model().objects.create_user(
            username="other-bind", tenant=other_tenant, user_type="internal", is_active=True,
        )
        denied = self.client.put(
            f"/api/internal/integrations/feishu/identities/system-users/{other_user.id}/bind/",
            {"open_id": "ou_forbidden"}, format="json",
        )
        self.assertEqual(denied.status_code, 404)

    @patch("apps.integrations.feishu_api.FeishuIdentityService")
    def test_confirm_binding_rejects_open_id_outside_current_candidates(self, service_class):
        colleague = get_user_model().objects.create_user(
            username="operator-tamper", tenant=self.tenant, user_type="internal", is_active=True,
        )
        service_class.return_value.find_candidates.return_value = [{
            "open_id": "ou_expected", "user_id": "u1", "union_id": "", "department_ids": [],
        }]
        response = self.client.put(
            f"/api/internal/integrations/feishu/identities/system-users/{colleague.id}/binding/",
            {"open_id": "ou_injected", "user_id": "attacker-controlled"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FeishuIdentity.objects.filter(user=colleague).exists())

    def test_feishu_candidate_service_uses_token_and_batch_lookup_and_masks_contacts(self):
        colleague = get_user_model().objects.create_user(
            username="operator-service", email="operator@example.com", phone="13800138000",
            tenant=self.tenant, user_type="internal", is_active=True,
        )
        connection = FeishuConnection.objects.create(
            tenant=self.tenant, app_id="cli_test", app_secret_ref="cred_test", enabled=True,
            created_by=self.user, updated_by=self.user,
        )
        custody = type("Custody", (), {"retrieve_secret": lambda self, ref: "never-return-this"})()
        http = type("Http", (), {})()
        http.request = Mock(side_effect=[
            FakeResponse({"code": 0, "tenant_access_token": "token-value"}),
            FakeResponse({"code": 0, "data": {"user_list": [{
                "user_id": "ou_123", "email": "operator@example.com", "mobile": "13800138000",
            }]}}),
            FakeResponse({"code": 0, "data": {"user": {
                "open_id": "ou_123", "user_id": "u_123", "union_id": "on_123", "name": "张三",
                "email": "operator@example.com", "mobile": "13800138000", "department_ids": ["od_1"],
            }}}),
        ])
        candidates = FeishuIdentityService(http=http, custody=custody).find_candidates(
            connection=connection, user=colleague,
        )
        self.assertEqual(candidates[0]["open_id"], "ou_123")
        self.assertEqual(candidates[0]["email"], "o*******@example.com")
        self.assertEqual(candidates[0]["phone"], "*******8000")
        self.assertEqual(candidates[0]["match_level"], "exact_contact")
        self.assertEqual(http.request.call_args_list[1].args[1], "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id")
        self.assertEqual(len(http.request.call_args_list), 3)
        self.assertNotIn("never-return-this", str(candidates))

    def test_feishu_candidate_service_falls_back_to_paginated_name_and_department_lookup(self):
        from apps.accounts.models import InternalUserProfile
        from apps.tenants.models import Department

        department = Department.objects.create(tenant=self.tenant, name="技术部")
        colleague = get_user_model().objects.create_user(
            username="operator-name", full_name="张三", email="missing@example.com",
            tenant=self.tenant, user_type="internal", is_active=True,
        )
        InternalUserProfile.objects.create(user=colleague, tenant=self.tenant, department=department)
        connection = FeishuConnection.objects.create(
            tenant=self.tenant, app_id="cli_test", app_secret_ref="cred_test", enabled=True,
            created_by=self.user, updated_by=self.user,
        )
        custody = type("Custody", (), {"retrieve_secret": lambda self, ref: "secret"})()
        http = type("Http", (), {})()
        http.request = Mock(side_effect=[
            FakeResponse({"code": 0, "tenant_access_token": "token-value"}),
            FakeResponse({"code": 0, "data": {"user_list": []}}),
            FakeResponse({"code": 0, "data": {"items": [], "has_more": False}}),
            FakeResponse({"code": 0, "data": {"items": [
                {"open_department_id": "od_tech", "name": "技术部"},
            ], "has_more": False}}),
            FakeResponse({"code": 0, "data": {"items": [
                {"open_id": "ou_name", "user_id": "u_name", "name": "张三",
                 "email": "zhangsan@example.com", "mobile": "13800138000",
                 "department_ids": ["od_tech"]},
            ], "has_more": False}}),
            FakeResponse({"code": 0, "data": {"items": [], "has_more": False}}),
        ])

        candidates = FeishuIdentityService(http=http, custody=custody).find_candidates(
            connection=connection, user=colleague,
        )

        self.assertEqual(candidates[0]["open_id"], "ou_name")
        self.assertEqual(candidates[0]["match_level"], "name_department")
        self.assertEqual(candidates[0]["match_reason"], "姓名与部门一致")
        self.assertEqual(candidates[0]["email"], "z*******@example.com")
        self.assertEqual(candidates[0]["phone"], "*******8000")
        requested_urls = [call.args[1] for call in http.request.call_args_list]
        self.assertTrue(any("departments/0/children" in url for url in requested_urls))
        self.assertTrue(any("find_by_department" in url and "od_tech" in url for url in requested_urls))
        self.assertNotIn("secret", str(candidates))

    def test_feishu_candidate_service_returns_controlled_reason_when_no_name_match(self):
        colleague = get_user_model().objects.create_user(
            username="operator-none", full_name="不存在", tenant=self.tenant,
            user_type="internal", is_active=True,
        )
        connection = FeishuConnection.objects.create(
            tenant=self.tenant, app_id="cli_test", app_secret_ref="cred_test", enabled=True,
            created_by=self.user, updated_by=self.user,
        )
        custody = type("Custody", (), {"retrieve_secret": lambda self, ref: "secret"})()
        http = type("Http", (), {})()
        http.request = Mock(side_effect=[
            FakeResponse({"code": 0, "tenant_access_token": "token-value"}),
            FakeResponse({"code": 0, "data": {"items": [], "has_more": False}}),
            FakeResponse({"code": 0, "data": {"items": [], "has_more": False}}),
        ])
        with self.assertRaises(ValidationError) as caught:
            FeishuIdentityService(http=http, custody=custody).find_candidates(
                connection=connection, user=colleague,
            )
        self.assertEqual(caught.exception.detail["reason"], "no_matching_feishu_user")
        self.assertIn("未找到匹配", str(caught.exception.detail["message"]))

    def test_feishu_candidate_service_requires_email_or_phone(self):
        colleague = get_user_model().objects.create_user(
            username="operator-no-contact", tenant=self.tenant, user_type="internal", is_active=True,
        )
        with self.assertRaisesMessage(Exception, "未配置姓名、邮箱或手机号"):
            FeishuIdentityService(http=object(), custody=object()).find_candidates(
                connection=None, user=colleague,
            )

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
