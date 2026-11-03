from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations.product_images import shopee_image, lazada_image, tiktok_image
from apps.integrations.platform_product_ingestion import upsert_platform_product
from apps.listings.models import PlatformProductDetail
from apps.listings.serializers import PlatformProductDetailSerializer
from apps.integrations.readonly_clients import ShopeeReadonlyClient, LazadaReadonlyClient, TikTokReadonlyClient
from tests.test_platform_product_ingestion import _fixture, _record


SP_MAIN = "https://cf.shopee.ph/file/synthetic-main"
SP_RED = "https://down-ph.img.susercontent.com/file/synthetic-red"
SP_BLUE = "https://down-ph.img.susercontent.com/file/synthetic-blue"
LZ = "https://img.lazcdn.com/g/p/synthetic-red.jpg"
TK = "https://p16-oec-sg.ibyteimg.com/synthetic-red.jpg"


def test_shopee_variant_image_follows_its_tier_index_not_the_first_other_variant():
    product = {"image": {"image_url_list": [SP_MAIN]}}
    body = {"tier_variation": [{"option_list": [{"image": {"image_url": SP_RED}}, {"image": {"image_url": SP_BLUE}}]}]}
    assert shopee_image(product, {"tier_index": [1]}, body) == {"platform_image_url": SP_BLUE, "platform_image_source": "variant"}
    assert shopee_image(product, {"tier_index": [99]}, body) == {"platform_image_url": SP_MAIN, "platform_image_source": "product"}
    assert shopee_image(product)["platform_image_url"] == SP_MAIN


def test_standardized_shopee_variation_images_and_zero_index():
    body = {"standardise_tier_variation": [{"variation_option_list": [{"image_url": SP_RED}, {"image_url": SP_BLUE}]}]}
    assert shopee_image({}, {"tier_index": [0]}, body)["platform_image_url"] == SP_RED
    assert shopee_image({}, {"tier_index": [1]}, body)["platform_image_url"] == SP_BLUE


def test_lazada_and_tiktok_prefer_exact_variant_image():
    assert lazada_image({"images": ["https://my-live.slatic.net/p/synthetic-main.jpg"]}, {"Images": [LZ]}) == {
        "platform_image_url": LZ, "platform_image_source": "variant"}
    assert tiktok_image({"main_images": [{"urls": ["https://p16-oec-sg.ibyteimg.com/synthetic-main.jpg"]}]},
        {"sales_attributes": [{"sku_img": {"urls": [TK]}}]}) == {"platform_image_url": TK, "platform_image_source": "variant"}
    assert tiktok_image({"main_images": [{"urls": [TK]}]}, {})["platform_image_source"] == "product"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:image/svg+xml,x", "http://cf.shopee.ph/file/x",
    "https://127.0.0.1/x", "https://localhost/x", "https://user:password@cf.shopee.ph/file/x",
    "https://cf.shopee.ph.attacker.test/x", "https://example.test/image.jpg"])
def test_untrusted_image_urls_are_not_accepted(url):
    assert shopee_image({"image": {"image_url_list": [url]}}) == {}


def test_absent_and_explicit_empty_images_are_different():
    assert shopee_image({}) == lazada_image({}, {}) == tiktok_image({}, {}) == {}
    assert shopee_image({"image": {"image_url_list": []}}) == {"platform_image_url": "", "platform_image_source": ""}
    assert lazada_image({}, {"Images": []}) == {"platform_image_url": "", "platform_image_source": ""}
    assert tiktok_image({"main_images": []}, {}) == {"platform_image_url": "", "platform_image_source": ""}


def test_client_paths_pass_platform_images_into_normalized_records():
    shopee = ShopeeReadonlyClient(SimpleNamespace(platform="shopee", platform_config={}), custody=Mock())
    def sp_request(path, query):
        if path == shopee.PRODUCT_LIST_PATH:
            return {"response": {"item": [{"item_id": "1"}], "has_next_page": False}}
        return {"response": {"item_list": [{"item_id": "1", "has_model": False, "image": {"image_url_list": [SP_MAIN]}}]}}
    shopee._request = sp_request
    assert shopee.fetch_products("", {"page_size": 1, "time_from": 1, "time_to": 2})["records"][0]["platform_image_url"] == SP_MAIN
    assert shopee.fetch_products_by_ids(["1"])["records"][0]["platform_image_url"] == SP_MAIN
    lazada = LazadaReadonlyClient(SimpleNamespace(platform="lazada", platform_config={}), custody=Mock())
    lazada._request = lambda *a: {"data": {"products": [{"item_id": "1", "skus": [{"SkuId": "2", "Images": [LZ]}]}], "total_products": 1}}
    assert lazada.fetch_products("", {"page_size": 1})["records"][0]["platform_image_url"] == LZ
    tiktok = TikTokReadonlyClient(SimpleNamespace(platform="tiktok", platform_config={}), authorization=SimpleNamespace(shop_cipher="synthetic"), custody=Mock())
    def tk_request(path, **kwargs):
        if path == tiktok.PRODUCT_SEARCH_PATH:
            return {"data": {"products": [{"id": "1"}]}}
        return {"data": {"id": "1", "main_images": [{"urls": [TK]}], "skus": [{"id": "2"}]}}
    tiktok._request = tk_request
    assert tiktok.fetch_products("", {"page_size": 1})["records"][0]["platform_image_url"] == TK


@pytest.mark.django_db
def test_image_ingestion_does_not_overwrite_internal_sku_and_preserves_omitted_images():
    ctx = _fixture()
    ctx["sku"].image_url = "/media/original-internal-sku.jpg"
    ctx["sku"].save(update_fields=["image_url"])
    record = _record(platform_image_url=SP_RED, platform_image_source="variant")
    upsert_platform_product(ctx["job"], record)
    detail = PlatformProductDetail.objects.get(tenant=ctx["tenant"])
    assert detail.platform_image_url == SP_RED and detail.platform_image_source == "variant"
    ctx["sku"].refresh_from_db()
    assert ctx["sku"].image_url == "/media/original-internal-sku.jpg"
    upsert_platform_product(ctx["job"], _record())
    detail.refresh_from_db()
    assert detail.platform_image_url == SP_RED
    upsert_platform_product(ctx["job"], _record(platform_image_url="", platform_image_source=""))
    detail.refresh_from_db()
    assert detail.platform_image_url == ""


@pytest.mark.django_db
def test_images_are_read_only_in_regular_detail_edits():
    ctx = _fixture()
    upsert_platform_product(ctx["job"], _record(platform_image_url=SP_MAIN, platform_image_source="product"))
    detail = PlatformProductDetail.objects.get(tenant=ctx["tenant"])
    serializer = PlatformProductDetailSerializer(detail, data={"platform_image_url": SP_BLUE, "platform_image_source": "variant"}, partial=True)
    serializer.is_valid(raise_exception=True)
    assert "platform_image_url" not in serializer.validated_data
    assert "platform_image_source" not in serializer.validated_data


@pytest.mark.django_db
def test_stale_and_status_only_snapshots_do_not_replace_image():
    ctx = _fixture()
    stamp = timezone.now()
    upsert_platform_product(ctx["job"], _record(platform_image_url=SP_RED, platform_image_source="variant", platform_updated_at=stamp))
    upsert_platform_product(ctx["job"], _record(platform_image_url=SP_BLUE, platform_image_source="variant", platform_updated_at=stamp-timedelta(seconds=1)))
    detail = PlatformProductDetail.objects.get(tenant=ctx["tenant"])
    assert detail.platform_image_url == SP_RED
    upsert_platform_product(ctx["job"], _record(status_only=True, sales_status="DELETED", platform_image_url=SP_BLUE,
        platform_image_source="variant", platform_updated_at=stamp+timedelta(seconds=1)))
    detail.refresh_from_db()
    assert detail.sales_status == "DELETED" and detail.platform_image_url == SP_RED
