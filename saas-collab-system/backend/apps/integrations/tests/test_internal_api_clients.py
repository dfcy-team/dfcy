from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APITestCase

from apps.permissions.models import Permission, Role, UserRole
from apps.tenants.models import Tenant

from apps.integrations.models import InternalAPIClient, InternalAPIClientAudit


class InternalAPIClientTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="IAC01", name="Internal API tenant")
        self.other_tenant = Tenant.objects.create(code="IAC02", name="Other tenant")
        self.user = get_user_model().objects.create_user(
            username="internal-api-admin", password="x", tenant=self.tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-admin", password="x", tenant=self.other_tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        self.client.force_authenticate(self.user)
        self.payload = {
            "name": "Knowledge base",
            "caller_type": "knowledge_base",
            "resources": {"products": ["id", "sku", "updated_at"], "suppliers": ["id", "name"]},
            "allowed_cidrs": ["10.10.0.0/16"],
            "rate_limit_per_minute": 120,
            "page_size_limit": 200,
            "status": "active",
        }

    def create_client(self):
        response = self.client.post("/api/internal/integrations/internal-api-clients/", self.payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response

    def test_create_returns_secret_once_and_only_hash_is_persisted(self):
        response = self.create_client()
        data = response.json()["data"]
        secret = data["client_secret"]
        obj = InternalAPIClient.objects.get(pk=data["id"])
        self.assertTrue(check_password(secret, obj.secret_hash))
        self.assertNotEqual(secret, obj.secret_hash)
        self.assertNotIn(secret, str(self.client.get("/api/internal/integrations/internal-api-clients/").json()))
        self.assertNotIn(secret, str(self.client.get(f"/api/internal/integrations/internal-api-clients/{obj.pk}/").json()))
        self.assertEqual(obj.audit_logs.get().action, "created")

    def test_update_status_rotation_and_audit_are_closed_loop(self):
        obj_id = self.create_client().json()["data"]["id"]
        updated = self.client.patch(
            f"/api/internal/integrations/internal-api-clients/{obj_id}/",
            {"page_size_limit": 50, "resources": {"purchase_orders": ["id", "status"]}}, format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        disabled = self.client.post(
            f"/api/internal/integrations/internal-api-clients/{obj_id}/status/", {"status": "disabled"}, format="json"
        )
        self.assertEqual(disabled.status_code, 200, disabled.content)
        rotated = self.client.post(
            f"/api/internal/integrations/internal-api-clients/{obj_id}/rotate/", {},
            format="json", HTTP_IDEMPOTENCY_KEY="rotation-1",
        )
        self.assertEqual(rotated.status_code, 200, rotated.content)
        secret = rotated.json()["data"]["client_secret"]
        replay = self.client.post(
            f"/api/internal/integrations/internal-api-clients/{obj_id}/rotate/", {},
            format="json", HTTP_IDEMPOTENCY_KEY="rotation-1",
        )
        self.assertIsNone(replay.json()["data"]["client_secret"])
        self.assertTrue(replay.json()["data"]["idempotent_replay"])
        obj = InternalAPIClient.objects.get(pk=obj_id)
        self.assertTrue(check_password(secret, obj.secret_hash))
        audit = self.client.get(f"/api/internal/integrations/internal-api-clients/{obj_id}/audit/")
        self.assertEqual(audit.status_code, 200, audit.content)
        self.assertEqual({item["action"] for item in audit.json()["data"]["items"]}, {"created", "updated", "disabled", "secret_rotated"})

    def test_cross_tenant_detail_actions_and_audit_are_404(self):
        obj_id = self.create_client().json()["data"]["id"]
        self.client.force_authenticate(self.other_user)
        for method, suffix, payload in (
            (self.client.get, "", None),
            (self.client.patch, "", {"name": "stolen"}),
            (self.client.post, "status/", {"status": "disabled"}),
            (self.client.post, "rotate/", {"operation_id": "x"}),
            (self.client.get, "audit/", None),
        ):
            response = method(f"/api/internal/integrations/internal-api-clients/{obj_id}/{suffix}", payload, format="json") if payload is not None else method(f"/api/internal/integrations/internal-api-clients/{obj_id}/{suffix}")
            self.assertEqual(response.status_code, 404, response.content)

    def test_resource_field_cidr_and_limits_are_strictly_validated(self):
        bad_payloads = [
            {**self.payload, "resources": {"unknown": ["id"]}},
            {**self.payload, "resources": {"products": ["password"]}},
            {**self.payload, "allowed_cidrs": ["10.0.0.1/24"]},
            {**self.payload, "page_size_limit": 1001},
            {**self.payload, "rate_limit_per_minute": 0},
        ]
        for payload in bad_payloads:
            response = self.client.post("/api/internal/integrations/internal-api-clients/", payload, format="json")
            self.assertEqual(response.status_code, 400, response.content)

    def test_permissions_fail_closed_without_scope_and_business_read_api_is_absent(self):
        limited = get_user_model().objects.create_user(
            username="limited-internal-api", password="x", tenant=self.tenant,
            user_type="internal", is_active=True,
        )
        role = Role.objects.create(tenant=self.tenant, name="Internal API viewer", code="internal-api-viewer")
        role.permissions.add(Permission.objects.get(code="integrations.internal_api_client.view"))
        UserRole.objects.create(tenant=self.tenant, user=limited, role=role)
        self.client.force_authenticate(limited)
        self.assertEqual(self.client.get("/api/internal/integrations/internal-api-clients/").status_code, 403)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/internal-readonly/v1/products/").status_code, 404)

    def test_audit_records_are_immutable(self):
        obj_id = self.create_client().json()["data"]["id"]
        audit = InternalAPIClientAudit.objects.get(client_id=obj_id)
        audit.action = "tampered"
        with self.assertRaises(DjangoValidationError):
            audit.save()
        with self.assertRaises(DjangoValidationError):
            audit.delete()
        with self.assertRaises(DjangoValidationError):
            InternalAPIClientAudit.objects.filter(pk=audit.pk).update(action="tampered")
