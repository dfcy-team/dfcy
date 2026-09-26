import base64

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.test import override_settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APITestCase

from apps.permissions.models import Permission, Role, UserRole
from apps.tenants.models import Tenant

from apps.integrations.models import InternalAPIClient, InternalAPIClientAudit
from apps.integrations.serializers import INTERNAL_API_RESOURCE_FIELDS
from apps.integrations.internal_readonly_api import _source_ip
from apps.products.models import ProductSPU


class InternalAPIClientTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="IAC01", name="Internal API tenant")
        self.other_tenant = Tenant.objects.create(code="IAC02", name="Other tenant")
        self.user = get_user_model().objects.create_user(
            username="internal-api-admin", password=None, tenant=self.tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-admin", password=None, tenant=self.other_tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        self.client.force_authenticate(self.user)
        self.payload = {
            "name": "Knowledge base",
            "caller_type": "internal_system",
            "resources": ["products", "suppliers"],
            "allowed_cidrs": ["10.10.0.0/16"],
            "rate_limit_per_minute": 120,
            "page_size_limit": 200,
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
        self.assertEqual(set(obj.resources["products"]), INTERNAL_API_RESOURCE_FIELDS["products"])
        self.assertEqual(set(obj.resources["suppliers"]), INTERNAL_API_RESOURCE_FIELDS["suppliers"])

    def test_update_status_rotation_and_audit_are_closed_loop(self):
        obj_id = self.create_client().json()["data"]["id"]
        updated = self.client.patch(
            f"/api/internal/integrations/internal-api-clients/{obj_id}/",
            {"page_size_limit": 50, "resources": ["purchase_orders"]}, format="json",
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
        self.assertEqual({item["action"] for item in audit.json()["data"]["items"]}, {"created", "updated", "secret_rotated"})

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

    def test_resource_cidr_and_limits_are_strictly_validated(self):
        bad_payloads = [
            {**self.payload, "caller_type": "knowledge_base"},
            {**self.payload, "resources": ["unknown"]},
            {**self.payload, "resources": {"products": ["password"]}},
            {**self.payload, "resources": []},
            {**self.payload, "allowed_cidrs": ["10.0.0.1/24"]},
            {**self.payload, "page_size_limit": 1001},
            {**self.payload, "rate_limit_per_minute": 0},
        ]
        for payload in bad_payloads:
            response = self.client.post("/api/internal/integrations/internal-api-clients/", payload, format="json")
            self.assertEqual(response.status_code, 400, response.content)

    def test_cidr_rejection_includes_field_detail_and_existing_knowledge_base_can_be_converted(self):
        response = self.client.post(
            "/api/internal/integrations/internal-api-clients/",
            {**self.payload, "allowed_cidrs": ["27.154.92.0/16"]}, format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("allowed_cidrs", response.json()["data"])

        legacy = InternalAPIClient.objects.create(
            tenant=self.tenant, created_by=self.user, updated_by=self.user,
            name="Legacy knowledge base", caller_type="knowledge_base",
            client_id="intapi_legacy", resources={"products": ["id"]},
            allowed_cidrs=["10.20.0.0/16"],
        )
        updated = self.client.patch(
            f"/api/internal/integrations/internal-api-clients/{legacy.pk}/",
            {"caller_type": "internal_system"}, format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["data"]["caller_type"], "internal_system")
        self.assertEqual(updated.json()["data"]["resources"]["products"], ["id"])

    def test_legacy_field_list_is_accepted_but_updated_block_uses_all_readable_fields(self):
        response = self.client.post(
            "/api/internal/integrations/internal-api-clients/",
            {**self.payload, "resources": {"products": ["id"]}}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(set(response.json()["data"]["resources"]["products"]), INTERNAL_API_RESOURCE_FIELDS["products"])

    def test_extended_business_resource_catalog_is_supported(self):
        resources = [
            "platform_products", "stores", "warehouses", "supplier_shipments", "sales_orders",
            "sales_returns", "inventory_snapshots", "shipments", "influencers", "outreach_tasks",
            "sample_fulfillments", "product_details", "product_mappings", "product_costs",
            "advertising_overview", "advertising_performance", "advertising_reconciliation",
            "product_research", "finance_imports", "analytics_overview", "basic_reports",
            "approval_records", "rpa_runs",
        ]
        response = self.client.post(
            "/api/internal/integrations/internal-api-clients/",
            {**self.payload, "name": "Extended reader", "resources": resources},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_resources = response.json()["data"]["resources"]
        self.assertEqual(set(saved_resources), set(resources))
        for resource in resources:
            self.assertEqual(set(saved_resources[resource]), INTERNAL_API_RESOURCE_FIELDS[resource])

    def test_permissions_fail_closed_without_scope_and_machine_auth(self):
        limited = get_user_model().objects.create_user(
            username="limited-internal-api", password=None, tenant=self.tenant,
            user_type="internal", is_active=True,
        )
        role = Role.objects.create(tenant=self.tenant, name="Internal API viewer", code="internal-api-viewer")
        role.permissions.add(Permission.objects.get(code="integrations.internal_api_client.view"))
        UserRole.objects.create(tenant=self.tenant, user=limited, role=role)
        self.client.force_authenticate(limited)
        self.assertEqual(self.client.get("/api/internal/integrations/internal-api-clients/").status_code, 403)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/internal-readonly/v1/products/").status_code, 401)

    def test_separate_review_then_enable_and_tenant_scoped_read(self):
        created = self.create_client().json()["data"]
        client_id = created["id"]
        self.assertEqual(created["status"], "disabled")
        self.assertEqual(created["approval_status"], "pending")
        credential = base64.b64encode(f'{created["client_id"]}:{created["client_secret"]}'.encode()).decode()
        header = {"HTTP_AUTHORIZATION": f"Basic {credential}", "REMOTE_ADDR": "10.10.1.2"}
        url = "/api/internal-readonly/v1/products/"
        self.assertEqual(self.client.get(url, **header).status_code, 401)
        self.assertEqual(self.client.post(f"/api/internal/integrations/internal-api-clients/{client_id}/status/", {"status": "active"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/internal/integrations/internal-api-clients/{client_id}/review/", {"decision": "approve"}, format="json").status_code, 400)
        reviewer = get_user_model().objects.create_user(username="independent-reviewer", password=None, tenant=self.tenant, user_type="internal", is_active=True, is_superuser=True)
        self.client.force_authenticate(reviewer)
        approved = self.client.post(f"/api/internal/integrations/internal-api-clients/{client_id}/review/", {"decision": "approve"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["data"]["status"], "disabled")
        self.client.force_authenticate(self.user)
        enabled = self.client.post(f"/api/internal/integrations/internal-api-clients/{client_id}/status/", {"status": "active"}, format="json")
        self.assertEqual(enabled.status_code, 200, enabled.content)
        ProductSPU.objects.create(tenant=self.tenant, spu_code="OWN", product_name="Own product")
        ProductSPU.objects.create(tenant=self.other_tenant, spu_code="OTHER", product_name="Other product")
        response = self.client.get(url, **header)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item["spu_code"] for item in response.json()["data"]["items"]], ["OWN"])
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=header["HTTP_AUTHORIZATION"], REMOTE_ADDR="8.8.8.8").status_code, 401)
        self.assertEqual(self.client.post(url, {}, format="json", **header).status_code, 405)
        self.assertEqual(self.client.get("/api/internal-readonly/v1/product_costs/", **header).status_code, 404)
        changed = self.client.patch(f"/api/internal/integrations/internal-api-clients/{client_id}/", {"name": "Renamed reader"}, format="json")
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.json()["data"]["approval_status"], "pending")
        self.assertEqual(self.client.get(url, **header).status_code, 401)

    def test_secret_rotation_does_not_let_config_editor_approve_their_changes(self):
        client_id = self.create_client().json()["data"]["id"]
        editor = get_user_model().objects.create_user(
            username="config-editor", password=None, tenant=self.tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        rotator = get_user_model().objects.create_user(
            username="credential-rotator", password=None, tenant=self.tenant,
            user_type="internal", is_active=True, is_superuser=True,
        )
        url = f"/api/internal/integrations/internal-api-clients/{client_id}/"
        self.client.force_authenticate(editor)
        self.assertEqual(self.client.patch(url, {"name": "Edited configuration"}, format="json").status_code, 200)
        self.client.force_authenticate(rotator)
        self.assertEqual(self.client.post(url + "rotate/", {}, format="json", HTTP_IDEMPOTENCY_KEY="rotation-after-edit").status_code, 200)
        self.client.force_authenticate(editor)
        self.assertEqual(self.client.post(url + "review/", {"decision": "approve"}, format="json").status_code, 400)
        self.assertEqual(InternalAPIClient.objects.get(pk=client_id).approval_status, "pending")

    def test_read_limit_is_enforced_and_capability_catalog_is_not_data(self):
        created = self.create_client().json()["data"]
        obj = InternalAPIClient.objects.get(pk=created["id"])
        obj.approval_status = "approved"
        obj.status = "active"
        obj.rate_limit_per_minute = 1
        obj.page_size_limit = 1
        obj.save()
        credential = base64.b64encode(f'{created["client_id"]}:{created["client_secret"]}'.encode()).decode()
        header = {"HTTP_AUTHORIZATION": f"Basic {credential}", "REMOTE_ADDR": "10.10.1.2"}
        url = "/api/internal-readonly/v1/products/"
        self.assertEqual(self.client.get(url + "?limit=2", **header).status_code, 400)
        self.assertEqual(self.client.get(url + "?limit=1", **header).status_code, 200)
        self.assertEqual(self.client.get(url + "?limit=1", **header).status_code, 429)

    def test_capabilities_mark_unpublished_blocks_pending(self):
        response = self.client.get("/api/internal-readonly/v1/capabilities/")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertIn("products", [item["code"] for item in data["ready_resources"]])
        self.assertIn("advertising_performance", data["pending_resources"])

    def test_forwarded_ip_only_from_explicitly_trusted_proxy(self):
        request = type("Request", (), {"META": {"REMOTE_ADDR": "8.8.8.8", "HTTP_X_FORWARDED_FOR": "10.10.1.2"}})()
        self.assertEqual(str(_source_ip(request)), "8.8.8.8")
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        with override_settings(INTERNAL_READONLY_TRUSTED_PROXY_CIDRS=["127.0.0.1/32"]):
            self.assertEqual(str(_source_ip(request)), "10.10.1.2")

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
