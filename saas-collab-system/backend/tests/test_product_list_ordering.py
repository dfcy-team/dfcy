import pytest
from django.core.cache import cache
from apps.products.models import ProductLegacyItem, ProductSPU
from tests.test_product_detail_read_efficiency import _fixture, _client

pytestmark = pytest.mark.django_db

@pytest.mark.parametrize("field", ["legacy_spu_code", "legacy_sku_code", "spu_code", "sku_code", "sku_product_name", "spu_product_name"])
def test_detail_sort_across_pages_and_cached_directions(field):
    cache.clear()
    tenant, user, legacy, skus = _fixture("sort-detail", size=8)
    ProductLegacyItem.objects.filter(pk=legacy[0].pk).update(legacy_spu_code="ZZ-OLD")
    ProductLegacyItem.objects.filter(pk=legacy[1].pk).update(legacy_sku_code=None)
    client = _client(user)
    url = "/api/internal/products/details/"
    baseline = client.get(url, {"page_size": 100}).json()["data"]["results"]
    for prefix in ("", "-"):
        rows = []
        for page in range(1, 6):
            response = client.get(url, {"ordering": prefix + field, "page_size": 3, "page": page})
            assert response.status_code == 200
            rows.extend(response.json()["data"]["results"])
        assert len(rows) == len(baseline) == 15
        assert len({(r["row_type"], r["id"]) for r in rows}) == 15
        values = [r[field] for r in rows]
        assert values == sorted(values, reverse=bool(prefix))
    invalid = client.get(url, {"ordering": "generated_sku__tenant__name", "page_size": 100})
    assert invalid.json()["data"]["results"] == baseline

@pytest.mark.parametrize("field", ["legacy_spu_code", "spu_code", "product_name"])
def test_spu_sort_before_pagination(field):
    tenant, user, _, _ = _fixture("sort-spu", size=1)
    ProductSPU.objects.create(tenant=tenant, spu_code="AAA", legacy_spu_code="ZZZ", product_name="ZZZ")
    ProductSPU.objects.create(tenant=tenant, spu_code="ZZZ", legacy_spu_code="AAA", product_name="AAA")
    client = _client(user)
    for prefix in ("", "-"):
        response = client.get("/api/internal/products/spus/", {"ordering": prefix + field, "page_size": 1})
        assert response.status_code == 200
        expected = ProductSPU.objects.filter(tenant=tenant).order_by(prefix + field, "-id").first()
        assert response.json()["data"]["results"][0]["id"] == expected.id


def test_spu_edit_invalidates_detail_sort_keys():
    cache.clear()
    tenant, user, _, skus = _fixture("sort-cache", size=1)
    from apps.products.models import ProductSKU
    other_spu = ProductSPU.objects.create(tenant=tenant, spu_code="OTHER", product_name="ZZZ")
    other_sku = ProductSKU.objects.create(tenant=tenant, spu=other_spu, sku_code="OTHER-SKU")
    client = _client(user)
    params = {"ordering": "spu_product_name", "page_size": 1}
    first = client.get("/api/internal/products/details/", params).json()["data"]["results"][0]
    assert first["sku_id"] == skus[0].id
    other_spu.product_name = "!!!First"
    other_spu.save(update_fields=["product_name", "updated_at"])
    updated = client.get("/api/internal/products/details/", params).json()["data"]["results"][0]
    assert updated["sku_id"] == other_sku.id
