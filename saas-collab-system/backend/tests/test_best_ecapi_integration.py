from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.exceptions import ValidationError, PermissionDenied

from apps.tenants.models import Tenant
from apps.masterdata.models import PlatformMaster, WarehouseMaster
from apps.integrations import best_access
from apps.integrations.best_ecapi import BestEcapiClient, signature, prepare_operation, OPERATIONS
from apps.integrations.models import WarehouseAuthorization, PlatformIntegrationConfig, IntegrationAuditLog
from apps.integrations.subject_access_service import _warehouse_provider
from apps.integrations.adapters import BestInventoryAdapter, get_adapter_for_config, JifengInventoryAdapter


class BestConfigurationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="best-test", name="Test")
        self.actor = get_user_model().objects.create(username="best-test", tenant=self.tenant)
        platform = PlatformMaster.objects.create(
            tenant=self.tenant, code="BEST", name="百世", platform_type="warehouse_third_party",
            warehouse_connector_state="selected", warehouse_connector_key="best_ecapi",
        )
        self.warehouse = WarehouseMaster.objects.create(tenant=self.tenant, code="BEST-PH", name="百世菲律宾仓",
            country_code="PH", warehouse_type="third_party", service_platform=platform)
        self.payload = {"partner_id": "TEST-P", "partner_key": "TEST-SECRET-ONLY", "customer_code": "TEST-C",
            "warehouse_code": "TEST-W", "gateway": "https://warehouse.example.test/ecapi/api/process",
            "version": 0, "idempotency_key": "TEST-SAVE-001"}
        self.custody = Mock()
        self.custody.store_secrets.return_value = self.custody.rotate_secrets.return_value = {
            "credential_id": "test-custody-secret-ref", "token_id": "test-custody-token-ref", "reference_version": 1}

    def invoke(self, method="get", payload=None, warehouse_id=None, allowed=True):
        request = getattr(APIRequestFactory(), method)("/", payload or {}, format="json")
        force_authenticate(request, self.actor)
        with patch.object(best_access, "check_user_permission", return_value=allowed), \
             patch.object(best_access, "integration_values_allowed", return_value=allowed), \
             patch("apps.integrations.credential_service.get_custody_backend", return_value=self.custody), \
             patch("apps.integrations.net_guard.PlatformHttpClient.request", side_effect=AssertionError("no real network")):
            return best_access.access(request, pk=warehouse_id or self.warehouse.pk)

    def test_first_check_promotes_config_and_binding_without_import(self):
        self.invoke("post", self.payload)
        request = APIRequestFactory().post("/", {"sku_code": "A"}, format="json")
        force_authenticate(request, self.actor)
        with patch.object(best_access, "check_user_permission", return_value=True), \
             patch.object(best_access, "integration_values_allowed", return_value=True), \
             patch("apps.integrations.best_ecapi.BestEcapiClient") as client:
            client.return_value.fetch_inventory.return_value = {"records": [{"itemSkuCode": "A"}]}
            response = best_access.check_connection(request, pk=self.warehouse.pk)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(client.call_args.kwargs["verification_only"])
        binding = WarehouseAuthorization.objects.get(warehouse=self.warehouse)
        self.assertEqual(binding.validation_status, "verified")
        self.assertEqual(binding.integration_config.status, "verified")
        self.assertFalse(binding.integration_config.sync_read_enabled)

    def test_save_uses_existing_binding_and_custody_without_enabling_network(self):
        self.assertEqual(_warehouse_provider(self.warehouse), "best_ecapi")
        response = self.invoke("post", self.payload)
        self.assertEqual(response.status_code, 200, response.data)
        record = WarehouseAuthorization.objects.get()
        self.assertEqual(record.provider, "best_ecapi")
        self.assertEqual(record.validation_status, "pending")
        config = record.integration_config
        self.assertFalse(config.network_enabled or config.sync_read_enabled or config.sync_write_enabled)
        self.assertNotIn("TEST-SECRET-ONLY", str(response.data))
        self.assertNotIn("TEST-SECRET-ONLY", str(config.platform_config))
        self.assertNotIn("TEST-SECRET-ONLY", str(list(IntegrationAuditLog.objects.values("masked_detail"))))
        self.custody.store_secrets.assert_called_once()
        self.assertEqual(self.invoke().data["data"]["warehouse_code"], "TEST-W")

    def test_update_retains_key_and_invalidates_validation(self):
        saved = self.invoke("post", self.payload).data["data"]
        WarehouseAuthorization.objects.update(validation_status="verified", last_verified_at=timezone.now())
        response = self.invoke("post", {**self.payload, "partner_key": "", "version": saved["version"],
            "idempotency_key": "TEST-SAVE-002"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], "pending")
        self.assertIsNone(response.data["data"]["last_verified_at"])
        self.custody.store_secrets.assert_called_once()
        self.assertEqual(WarehouseAuthorization.objects.count(), 1)

    def test_scope_and_tenant_protection(self):
        self.assertEqual(self.invoke("post", self.payload, allowed=False).status_code, 403)
        other = Tenant.objects.create(code="best-other", name="Other")
        other_warehouse = WarehouseMaster.objects.create(tenant=other, code="other", name="Other", country_code="PH", warehouse_type="owned")
        self.assertEqual(self.invoke(warehouse_id=other_warehouse.pk).status_code, 404)
        self.assertFalse(PlatformIntegrationConfig.objects.exists())
        self.custody.store_secrets.assert_not_called()

    def test_invalid_gateway_and_missing_secret_leave_no_config(self):
        for changes in ({"gateway": "http://warehouse.example.test/ecapi/api/process"}, {"partner_key": ""},
                        {"gateway": "https://warehouse.example.test:99999/ecapi/api/process"}):
            response = self.invoke("post", {**self.payload, **changes})
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(PlatformIntegrationConfig.objects.exists())

    def test_stale_save_and_duplicate_identity_do_not_rotate_secrets(self):
        self.invoke("post", self.payload)
        self.assertEqual(self.invoke("post", self.payload).status_code, 409)
        another = WarehouseMaster.objects.create(tenant=self.tenant, code="BEST-OTHER", name="Other", country_code="PH",
            warehouse_type="third_party", service_platform=self.warehouse.service_platform)
        self.assertEqual(self.invoke("post", self.payload, warehouse_id=another.pk).status_code, 409)
        self.custody.store_secrets.assert_called_once()
        self.custody.rotate_secrets.assert_not_called()


class BestProtocolTests(SimpleTestCase):
    def make_client(self):
        config = SimpleNamespace(pk=1, tenant_id=1, platform="best_ecapi", platform_config={"partner_id": "TEST-P",
            "customer_code": "TEST-C", "api_host": "https://warehouse.example.test/ecapi/api/process"},
            credential_id="test-secret-ref", connect_timeout_seconds=3, read_timeout_seconds=8)
        auth = SimpleNamespace(external_warehouse_code="TEST-W", integration_config=config)
        http, custody = Mock(), Mock()
        custody.retrieve_secret.return_value = "TEST-KEY"
        http.request.return_value.status_code = 200
        http.request.return_value.text = '<response><result>true</result><products><product><itemSkuCode>A</itemSkuCode><totalQuantity>3</totalQuantity><normalQuantity>2</normalQuantity></product></products></response>'
        return BestEcapiClient(config, auth, http_client=http, custody=custody), http

    def test_disabled_before_secrets_or_network(self):
        client, http = self.make_client()
        with self.assertRaises(PermissionDenied):
            client.fetch_inventory(None, {"sku_codes": ["A"]})
        http.request.assert_not_called()
        client.custody.retrieve_secret.assert_not_called()

    @override_settings(WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
    def test_catalog_outbound_routes_and_exact_signature(self):
        xml = '<request><customerCode>TEST-C</customerCode><warehouseCode>TEST-W</warehouseCode></request>'
        for operation in OPERATIONS:
            client, http = self.make_client()
            with patch.object(client, "preflight"):
                client._signed_request("POST", operation.name, {"bizData": xml})
            sent = http.request.call_args.kwargs
            self.assertEqual(sent["form_body"], {"partnerID": "TEST-P", "serviceType": operation.name,
                "bizData": xml, "sign": signature(xml, "TEST-KEY")})
            self.assertFalse(sent["retry"])

    def test_scope_override_and_dtd_rejected(self):
        client, http = self.make_client()
        with patch.object(client, "preflight"), self.assertRaises(PermissionDenied):
            client._signed_request("POST", "WMS_SO_STATUS_QUERY", {"bizData": '<request><customerCode>TEST-C</customerCode><warehouseCode>OTHER</warehouseCode></request>'})
        http.request.assert_not_called()
        with self.assertRaises(ValidationError):
            prepare_operation("WMS_SO_STATUS_QUERY", {"bizData": '<!DOCTYPE x><request/>'})

    def test_first_verification_cannot_be_used_for_other_operations(self):
        client, http = self.make_client()
        client.verification_only = True
        with patch.object(client, "preflight"), self.assertRaises(PermissionDenied):
            client._signed_request("POST", "TW_SO_NOTIFY", {"bizData": "<request/>"})
        http.request.assert_not_called()

    def test_inventory_uses_fifty_sku_batches_and_no_missing_quantity_guess(self):
        client, http = self.make_client()
        with patch.object(client, "preflight"):
            page = client.fetch_inventory(None, {"sku_codes": ["A"] + [f"B{x}" for x in range(50)]})
        self.assertEqual(page["next_cursor"], "50")
        self.assertEqual(http.request.call_args.kwargs["form_body"]["bizData"].count('<itemSkuCode>'), 50)
        with self.assertRaises(ValidationError):
            client.fetch_inventory(None, {"sku_codes": []})
        adapter = BestInventoryAdapter(SimpleNamespace(platform="best_ecapi", platform_config={}, environment="production"))
        with self.assertRaises(ValidationError):
            adapter.normalize_record({"itemSkuCode": "A"})

    def test_adapter_routes_separately_from_jifeng(self):
        for platform, expected in (("best_ecapi", BestInventoryAdapter), ("jifeng_wms", JifengInventoryAdapter)):
            self.assertIsInstance(get_adapter_for_config(SimpleNamespace(platform=platform, platform_config={}, environment="production"), "inventory_snapshot"), expected)

    def test_inventory_normalization_does_not_truncate_or_invent_reserved_stock(self):
        adapter = BestInventoryAdapter(SimpleNamespace(platform="best_ecapi", platform_config={}, environment="production"))
        adapter.warehouse_authorization = SimpleNamespace(warehouse_id=1, warehouse=SimpleNamespace(country_code="PH"))
        for value in ("1.5", "invalid", "-1", "NaN"):
            with self.assertRaises(ValidationError):
                adapter.normalize_record({"itemSkuCode": "A", "totalQuantity": value, "normalQuantity": "1"})
        record = adapter.normalize_record({"itemSkuCode": "A", "totalQuantity": "3", "normalQuantity": "2", "frozenQuantity": "1"})
        self.assertEqual(record["on_hand_qty"], 3)
        self.assertNotIn("reserved_qty", record["provided_quantity_fields"])
