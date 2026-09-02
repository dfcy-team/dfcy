from django.test import TestCase

from apps.listings.models import PlatformProductDetail
from apps.listings.platform_product_details import import_platform_product_ids
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


class PlatformProductIdImportTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")
        self.other_tenant = Tenant.objects.create(name="Tenant B", code="tenant-b")
        self.platform = PlatformMaster.objects.create(
            tenant=self.tenant, code="shopee", name="Shopee", platform_type="shopee",
        )
        self.store = StoreMaster.objects.create(
            tenant=self.tenant, platform=self.platform, code="shop-a", name="Shop A",
            country_code="PH", currency="PHP", timezone="Asia/Manila",
        )
        self.other_platform = PlatformMaster.objects.create(
            tenant=self.other_tenant, code="shopee", name="Shopee", platform_type="shopee",
        )
        self.other_store = StoreMaster.objects.create(
            tenant=self.other_tenant, platform=self.other_platform, code="shop-b", name="Shop B",
            country_code="PH", currency="PHP", timezone="Asia/Manila",
        )

    def _detail(self, tenant=None, store=None, variant="V-1", product=""):
        tenant = tenant or self.tenant
        store = store or self.store
        return PlatformProductDetail.objects.create(
            tenant=tenant, platform=store.platform, store=store,
            platform_variant_id=variant, platform_product_id=product,
        )

    def test_unique_variant_updates_and_same_product_is_unchanged(self):
        self._detail(variant="V-1")
        raw = "变体ID,平台商品ID\nV-1,P-100\n"

        first = import_platform_product_ids(tenant=self.tenant, raw=raw.encode("utf-8-sig"), filename="ids.csv")
        self.assertEqual(first["updated"], 1)
        self.assertEqual(first["unmatched"], 0)
        self.assertEqual(PlatformProductDetail.objects.get(platform_variant_id="V-1").platform_product_id, "P-100")

        second = import_platform_product_ids(tenant=self.tenant, raw=raw.encode("utf-8-sig"), filename="ids.csv")
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(second["updated"], 0)

    def test_product_id_can_be_shared_by_multiple_variants(self):
        self._detail(variant="V-1")
        self._detail(variant="V-2")
        raw = "变体ID,平台商品ID\nV-1,P-SHARED\nV-2,P-SHARED\n"

        result = import_platform_product_ids(tenant=self.tenant, raw=raw.encode("utf-8-sig"), filename="ids.csv")
        self.assertEqual(result["updated"], 2)
        self.assertEqual(set(PlatformProductDetail.objects.values_list("platform_product_id", flat=True)), {"P-SHARED"})

    def test_ambiguous_variant_is_skipped_and_other_tenant_is_invisible(self):
        self._detail(variant="V-DUP", product="OLD-A")
        second_store = StoreMaster.objects.create(
            tenant=self.tenant, platform=self.platform, code="shop-a-2", name="Shop A 2",
            country_code="PH", currency="PHP", timezone="Asia/Manila",
        )
        self._detail(store=second_store, variant="V-DUP", product="OLD-B")
        self._detail(tenant=self.other_tenant, store=self.other_store, variant="V-OTHER")
        raw = "变体ID,平台商品ID\nV-DUP,P-NEW\nV-OTHER,P-OTHER\nV-MISSING,P-MISSING\n"

        result = import_platform_product_ids(tenant=self.tenant, raw=raw.encode("utf-8-sig"), filename="ids.csv")
        self.assertEqual(result["ambiguous"], 1)
        self.assertEqual(result["unmatched"], 2)
        self.assertEqual(result["skipped"], 3)
        self.assertEqual(PlatformProductDetail.objects.filter(tenant=self.tenant, platform_product_id="P-NEW").count(), 0)
        self.assertEqual(PlatformProductDetail.objects.get(platform_variant_id="V-OTHER").platform_product_id, "")

    def test_empty_columns_are_reported(self):
        result = import_platform_product_ids(
            tenant=self.tenant,
            raw="变体ID,平台商品ID\n,P-1\nV-1,\n".encode("utf-8-sig"),
            filename="ids.csv",
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["errors"]), 2)

    def test_unmatched_response_has_bounded_sample_and_remaining_count(self):
        rows = "\n".join(
            f"V-MISSING-{index:03d},P-{index:03d}"
            for index in range(105)
        )
        result = import_platform_product_ids(
            tenant=self.tenant,
            raw=f"变体ID,平台商品ID\n{rows}\n".encode("utf-8-sig"),
            filename="ids.csv",
        )

        self.assertEqual(result["total"], 105)
        self.assertEqual(result["unmatched"], 105)
        self.assertEqual(result["unmatched_unique"], 105)
        self.assertEqual(len(result["unmatched_sample"]), 100)
        self.assertEqual(result["unmatched_sample"][0], "V-MISSING-000")
        self.assertEqual(result["unmatched_sample"][-1], "V-MISSING-099")
        self.assertEqual(result["unmatched_remaining"], 5)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["skipped"], 105)
