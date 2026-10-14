import base64
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.integrations.models import InternalAPIClient
from apps.integrations.serializers import INTERNAL_API_RESOURCE_FIELDS
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


class ProductCostReadonlyAPITests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="COSTA", name="Cost tenant")
        self.other = Tenant.objects.create(code="COSTB", name="Other cost tenant")
        self.user = get_user_model().objects.create_user(username="cost-reader-owner", tenant=self.tenant, user_type="internal", is_active=True)
        self.other_user = get_user_model().objects.create_user(username="cost-other-owner", tenant=self.other, user_type="internal", is_active=True)
        self.secret = "secret-value"
        self.client_obj = InternalAPIClient.objects.create(
            tenant=self.tenant, created_by=self.user, updated_by=self.user, name="Cost reader",
            caller_type="internal_system", client_id="cost_reader", secret_hash=make_password(self.secret),
            secret_prefix="secret", secret_fingerprint="f" * 64,
            resources={"product_costs": sorted(INTERNAL_API_RESOURCE_FIELDS["product_costs"])},
            allowed_cidrs=["10.10.0.0/16"], rate_limit_per_minute=100, page_size_limit=100,
            status="active", approval_status="approved",
        )
        credential = base64.b64encode(f"{self.client_obj.client_id}:{self.secret}".encode()).decode()
        self.headers = {"HTTP_AUTHORIZATION": f"Basic {credential}", "REMOTE_ADDR": "10.10.1.2"}
        self.url = "/api/internal-readonly/v1/product_costs/"
        self.spu = ProductSPU.objects.create(tenant=self.tenant, spu_code="SPU-1", legacy_spu_code="OLD-SPU", product_name="Widget")
        self.sku = ProductSKU.objects.create(tenant=self.tenant, spu=self.spu, sku_code="SKU-1", legacy_sku_code="OLD-SKU", product_name="Widget blue")
        self.warehouse = WarehouseMaster.objects.create(tenant=self.tenant, code="WH-1", name="Main", country_code="US", warehouse_type="owned")

    def make_cost(self, version, **kwargs):
        return ProductCostVersion.objects.create(
            tenant=self.tenant, sku=self.sku, created_by=self.user, version_no=version,
            effective_from=timezone.now() - timedelta(days=version), **kwargs,
        )

    def test_capabilities_and_canonical_catalog_are_published(self):
        from apps.integrations.internal_readonly_api import READY
        response = self.client.get("/api/internal-readonly/v1/capabilities/")
        cost = next(item for item in response.json()["data"]["ready_resources"] if item["code"] == "product_costs")
        self.assertEqual(cost["fields"], list(READY["product_costs"][1]))
        self.assertEqual(set(cost["fields"]), INTERNAL_API_RESOURCE_FIELDS["product_costs"])

    def test_returns_every_version_exact_decimal_strings_and_nullable_warehouse(self):
        self.make_cost(1, status="pending", source="manual", currency="EUR", purchase_cost="12.3400", freight_cost="0", duty_cost="1.2345", packaging_cost="2.3456", other_cost="3.4567", system_cost=None, confirmed_cost=None)
        self.make_cost(2, status="confirmed", source="import", currency="USD", warehouse=self.warehouse, purchase_cost="99.9999", freight_cost="0.0001", duty_cost="1.0001", packaging_cost="2.0002", other_cost="3.0003", system_cost="100.1000", confirmed_cost="100.0000", effective_to=timezone.now())
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        items = response.json()["data"]["items"]
        self.assertEqual([row["version_no"] for row in items], [1, 2])
        pending, confirmed = items
        self.assertEqual((pending["status"], pending["source"], pending["currency"], pending["purchase_cost"], pending["freight_cost"], pending["duty_cost"], pending["packaging_cost"], pending["other_cost"]), ("pending", "manual", "EUR", "12.3400", "0.0000", "1.2345", "2.3456", "3.4567"))
        self.assertIsNone(pending["system_cost"])
        self.assertIsNone(pending["confirmed_cost"])
        self.assertIsNone(pending["warehouse_id"])
        self.assertIsNone(pending["warehouse_code"])
        self.assertIsNone(pending["warehouse_name"])
        self.assertIsNone(pending["warehouse_country_code"])
        self.assertEqual((pending["sku_id"], pending["spu_id"], pending["sku_code"], pending["legacy_sku_code"], pending["spu_code"], pending["legacy_spu_code"], pending["product_name"]), (self.sku.pk, self.spu.pk, "SKU-1", "OLD-SKU", "SPU-1", "OLD-SPU", "Widget blue"))
        self.assertEqual((confirmed["warehouse_id"], confirmed["warehouse_code"], confirmed["warehouse_name"], confirmed["warehouse_country_code"], confirmed["currency"], confirmed["freight_cost"], confirmed["duty_cost"], confirmed["packaging_cost"], confirmed["other_cost"], confirmed["system_cost"], confirmed["confirmed_cost"]), (self.warehouse.pk, "WH-1", "Main", "US", "USD", "0.0001", "1.0001", "2.0002", "3.0003", "100.1000", "100.0000"))
        self.assertIsNotNone(confirmed["effective_to"])
        self.assertEqual(set(pending), INTERNAL_API_RESOURCE_FIELDS["product_costs"])
        self.assertEqual(set(confirmed), INTERNAL_API_RESOURCE_FIELDS["product_costs"])
        self.assertNotIn("tenant_id", pending)
        self.assertNotIn("created_by", pending)

    def test_tenant_guards_paging_permission_and_read_only_methods(self):
        own = self.make_cost(1)
        other_spu = ProductSPU.objects.create(tenant=self.other, spu_code="OTHER", product_name="Other")
        other_sku = ProductSKU.objects.create(tenant=self.other, spu=other_spu, sku_code="OTHER-SKU")
        ProductCostVersion.objects.create(tenant=self.other, sku=other_sku, created_by=self.other_user, version_no=1, effective_from=timezone.now())
        first = self.client.get(self.url + "?limit=1", **self.headers).json()["data"]
        self.assertEqual([row["id"] for row in first["items"]], [own.pk])
        self.assertFalse(first["has_more"])
        self.assertEqual(self.client.get(self.url + "?cursor=999999", **self.headers).json()["data"]["items"], [])
        before = list(ProductCostVersion.objects.order_by("id").values())
        for method in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            self.assertEqual(method(self.url, {}, format="json", **self.headers).status_code, 405)
        self.assertEqual(list(ProductCostVersion.objects.order_by("id").values()), before)
        self.client_obj.resources = {}
        self.client_obj.save(update_fields=["resources"])
        self.assertEqual(self.client.get(self.url, **self.headers).status_code, 403)

    def test_malformed_cross_tenant_relations_are_hidden(self):
        other_spu = ProductSPU.objects.create(tenant=self.other, spu_code="CROSS-SPU", product_name="Cross")
        other_sku = ProductSKU.objects.create(tenant=self.other, spu=other_spu, sku_code="CROSS-SKU")
        malformed_sku = ProductSKU.objects.create(tenant=self.tenant, spu=self.spu, sku_code="BAD-SKU")
        malformed_link = ProductSKU.objects.create(tenant=self.tenant, spu=self.spu, sku_code="BAD-SPU-LINK")
        ProductSKU.objects.filter(pk=malformed_link.pk).update(spu=other_spu)
        malformed_warehouse = WarehouseMaster.objects.create(tenant=self.other, code="OTHER-WH", name="Other", country_code="CA", warehouse_type="owned")
        ProductCostVersion.objects.bulk_create([
            ProductCostVersion(tenant=self.tenant, sku=other_sku, created_by=self.user, version_no=30, effective_from=timezone.now()),
            ProductCostVersion(tenant=self.tenant, sku=malformed_sku, warehouse=malformed_warehouse, created_by=self.user, version_no=31, effective_from=timezone.now()),
            ProductCostVersion(tenant=self.tenant, sku=malformed_link, created_by=self.user, version_no=32, effective_from=timezone.now()),
        ])
        self.assertEqual(self.client.get(self.url, **self.headers).json()["data"]["items"], [])

    def test_auth_expiry_disabled_pending_wrong_secret_and_cidr(self):
        good = self.headers.copy()
        bad_secret = base64.b64encode(b"cost_reader:wrong").decode()
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION=f"Basic {bad_secret}", REMOTE_ADDR="10.10.1.2").status_code, 401)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION=good["HTTP_AUTHORIZATION"], REMOTE_ADDR="8.8.8.8").status_code, 401)
        self.client_obj.expires_at = timezone.now() - timedelta(seconds=1)
        self.client_obj.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(self.url, **good).status_code, 401)
        self.client_obj.expires_at = None
        self.client_obj.status = "disabled"
        self.client_obj.save(update_fields=["expires_at", "status"])
        self.assertEqual(self.client.get(self.url, **good).status_code, 401)
        self.client_obj.status = "active"
        self.client_obj.approval_status = "pending"
        self.client_obj.save(update_fields=["status", "approval_status"])
        self.assertEqual(self.client.get(self.url, **good).status_code, 401)

    def test_legacy_field_list_normalizes_to_full_contract(self):
        from apps.integrations.serializers import InternalAPIClientSerializer
        for legacy in (
            ["amount"], ["id", "sku"], ["amount", "purchase_cost"],
            ["id", "product_id", "sku", "currency", "amount", "effective_at", "updated_at"],
        ):
            serializer = InternalAPIClientSerializer(instance=self.client_obj, data={"resources": {"product_costs": legacy}}, partial=True)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(set(serializer.validated_data["resources"]["product_costs"]), INTERNAL_API_RESOURCE_FIELDS["product_costs"])
        invalid = InternalAPIClientSerializer(instance=self.client_obj, data={"resources": {"product_costs": ["amount", "made_up"]}}, partial=True)
        self.assertFalse(invalid.is_valid())
        selected = InternalAPIClientSerializer(instance=self.client_obj, data={"resources": ["product_costs"]}, partial=True)
        self.assertTrue(selected.is_valid(), selected.errors)
        self.assertEqual(set(selected.validated_data["resources"]["product_costs"]), INTERNAL_API_RESOURCE_FIELDS["product_costs"])

    def test_existing_legacy_block_grant_reads_all_current_fields(self):
        cost = self.make_cost(1, purchase_cost="8.7654")
        self.client_obj.resources = {"product_costs": ["amount"]}
        self.client_obj.save(update_fields=["resources"])
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["data"]["items"][0]
        self.assertEqual((item["id"], item["purchase_cost"]), (cost.pk, "8.7654"))
        self.assertEqual(set(item), INTERNAL_API_RESOURCE_FIELDS["product_costs"])

    def test_paging_limits_and_no_cost_expansion(self):
        first = self.make_cost(1)
        self.make_cost(2)
        page_one = self.client.get(self.url + "?limit=1", **self.headers)
        self.assertEqual(page_one.status_code, 200)
        self.assertTrue(page_one.json()["data"]["has_more"])
        self.assertEqual(page_one.json()["data"]["next_cursor"], first.pk)
        page_two = self.client.get(self.url + f"?limit=1&cursor={first.pk}", **self.headers).json()["data"]
        self.assertFalse(page_two["has_more"])
        self.assertIsNone(page_two["next_cursor"])
        self.assertEqual(len(page_two["items"]), 1)
        empty_page = self.client.get(self.url + "?limit=1&cursor=999999", **self.headers).json()["data"]
        self.assertEqual(empty_page["items"], [])
        self.assertFalse(empty_page["has_more"])
        self.assertIsNone(empty_page["next_cursor"])
        for query in ("?limit=0", "?limit=101", "?limit=nope", "?cursor=-1"):
            self.assertEqual(self.client.get(self.url + query, **self.headers).status_code, 400)
        self.client_obj.resources = {
            resource: sorted(INTERNAL_API_RESOURCE_FIELDS[resource])
            for resource in ("product_costs", "products", "product_details")
        }
        self.client_obj.save(update_fields=["resources"])
        product = self.client.get("/api/internal-readonly/v1/products/", **self.headers)
        details = self.client.get("/api/internal-readonly/v1/product_details/", **self.headers)
        for response in (product, details):
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()["data"]["items"])
            for row in response.json()["data"]["items"]:
                self.assertFalse({"purchase_price", "purchase_cost", "freight_cost", "duty_cost", "packaging_cost", "other_cost", "system_cost", "confirmed_cost"} & set(row))

    def test_cost_reads_obey_minute_quota(self):
        from unittest.mock import patch

        self.client_obj.rate_limit_per_minute = 1
        self.client_obj.save(update_fields=["rate_limit_per_minute"])
        # Avoid crossing a real minute boundary between the two assertions.
        with patch("apps.integrations.internal_readonly_api.timezone.now", return_value=timezone.now()):
            self.assertEqual(self.client.get(self.url, **self.headers).status_code, 200)
            self.assertEqual(self.client.get(self.url, **self.headers).status_code, 429)
