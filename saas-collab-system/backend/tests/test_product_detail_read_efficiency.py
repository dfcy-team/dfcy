"""Product detail semantics and bounded database reads on synthetic rows."""
import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.permissions.models import DataScope, UserRole
from apps.products import views
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU, ProductSPU
from apps.tenants.models import Tenant
from tests.test_product_detail_collection import _user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _fixture(code, size=6):
    tenant = Tenant.objects.create(name=code, code=code)
    user = _user(tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"{code}-SPU", product_name="=Formula SPU")
    legacy = [
        ProductLegacyItem.objects.create(
            tenant=tenant, legacy_sku_code=f"{code}-OLD-{index}", product_name=f"Legacy {index}",
            purchase_price=Decimal("3.5000"),
        )
        for index in range(size)
    ]
    skus = [
        ProductSKU.objects.create(
            tenant=tenant, spu=spu, sku_code=f"{code}-SKU-{index}", product_name=f"@SKU {index}",
            purchase_price=Decimal("7.2500"), is_active=index % 2 == 0,
        )
        for index in range(size)
    ]
    # A deliberate id/time tie across streams exercises row_kind as the last
    # sort key. Database-generated ids may overlap because tables are separate.
    anchor = timezone.now().replace(microsecond=0)
    ProductLegacyItem.objects.filter(tenant=tenant).update(updated_at=anchor)
    ProductSKU.objects.filter(tenant=tenant).update(updated_at=anchor)
    ProductLegacyItem.objects.filter(pk=legacy[0].pk).update(
        generated_sku=skus[0], generated_spu=spu, updated_at=anchor - timedelta(days=3),
    )
    ProductSKU.objects.filter(pk=skus[0].pk).update(updated_at=anchor + timedelta(days=1))
    return tenant, user, legacy, skus


def _reference_keys(tenant):
    legacy = list(ProductLegacyItem.objects.filter(tenant=tenant).select_related("generated_sku"))
    linked_ids = {item.generated_sku_id for item in legacy if item.generated_sku_id is not None}
    keys = []
    for item in legacy:
        updated = item.updated_at
        if item.generated_sku is not None and item.generated_sku.tenant_id == item.tenant_id:
            updated = max(updated, item.generated_sku.updated_at)
        keys.append((updated, item.id, 0, "legacy"))
    keys.extend(
        (sku.updated_at, sku.id, 1, "sku")
        for sku in ProductSKU.objects.filter(tenant=tenant).exclude(pk__in=linked_ids)
    )
    return sorted(keys, key=lambda key: (-key[0].timestamp(), -key[1], key[2]))


@pytest.mark.django_db
def test_detail_page_matches_mixed_order_and_only_materializes_requested_keys(monkeypatch):
    cache.clear()
    tenant, user, _, _ = _fixture("bounded-detail", size=75)
    expected = _reference_keys(tenant)
    fetched_keys = []
    original_fetch = QuerySet._fetch_all

    def record_fetch(queryset):
        original_fetch(queryset)
        if queryset.query.combinator == "union" and queryset._result_cache is not None:
            fetched_keys.append(len(queryset._result_cache))

    monkeypatch.setattr(QuerySet, "_fetch_all", record_fetch)
    client = _client(user)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/internal/products/details/", {"page": 3, "page_size": 7})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 149
    assert [(row["id"], row["row_type"]) for row in data["results"]] == [
        (key[1], key[3]) for key in expected[14:21]
    ]
    assert fetched_keys and max(fetched_keys) == 7
    key_sql = [query["sql"].upper() for query in queries if "UNION ALL" in query["sql"].upper()]
    assert len(key_sql) == 1 and "LIMIT 7" in key_sql[0] and "OFFSET 14" in key_sql[0]
    assert "page=2" in data["previous"] and "page=4" in data["next"]
    with CaptureQueriesContext(connection) as repeated_queries:
        repeated = client.get("/api/internal/products/details/", {"page": 3, "page_size": 7})
    assert repeated.content == response.content
    assert not any("UNION ALL" in query["sql"].upper() for query in repeated_queries)
    assert len(repeated_queries) < len(queries)
    with CaptureQueriesContext(connection) as next_queries:
        next_page = client.get("/api/internal/products/details/", {"page": 4, "page_size": 7})
    assert next_page.status_code == 200
    assert not any(" AS \"__count\"" in query["sql"] or " AS `__count`" in query["sql"] for query in next_queries)
    clamped = client.get("/api/internal/products/details/", {"page": 999, "page_size": 7}).json()["data"]
    assert [(row["id"], row["row_type"]) for row in clamped["results"]] == [(key[1], key[3]) for key in expected[147:]]
    assert clamped["next"] is None and "page=21" in clamped["previous"]


@pytest.mark.django_db
def test_detail_scoped_exclusion_does_not_hide_a_sku_for_an_invisible_legacy_mapping():
    cache.clear()
    tenant, user, legacy, skus = _fixture("scoped-detail")
    ProductLegacyItem.objects.filter(pk=legacy[0].pk).update(generated_spu=None)
    hidden_spu = ProductSPU.objects.create(tenant=tenant, spu_code="HIDDEN-SPU")
    hidden_sku = ProductSKU.objects.create(tenant=tenant, spu=hidden_spu, sku_code="HIDDEN-SKU")
    ProductLegacyItem.objects.create(tenant=tenant, legacy_sku_code="HIDDEN-OLD", generated_sku=hidden_sku)
    role = UserRole.objects.get(user=user).role
    DataScope.objects.filter(role=role).update(
        scope_type=DataScope.ScopeType.CUSTOM, config={"sku_ids": [skus[1].id], "legacy_item_ids": [legacy[1].id]},
    )
    # The authorized pending mapping and SKU remain independently visible;
    # hidden generated rows and unrelated products cannot contribute keys.
    client = _client(user)
    response = client.get("/api/internal/products/details/", {"page_size": 20})
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 2
    assert {(row["row_type"], row["id"]) for row in response.json()["data"]["results"]} == {
        ("legacy", legacy[1].id), ("sku", skus[1].id),
    }
    exported = client.get("/api/internal/products/details/export/")
    text = exported.content.decode("utf-8-sig")
    assert legacy[1].legacy_sku_code in text and skus[1].sku_code in text
    assert "HIDDEN-OLD" not in text and "HIDDEN-SKU" not in text


@pytest.mark.django_db
def test_detail_only_excludes_links_in_the_effective_category_filter():
    cache.clear()
    tenant, user, legacy, skus = _fixture("category-detail")
    category = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Parent")
    child = ProductCategory.objects.create(tenant=tenant, parent=category, level=2, code="01", name="Child")
    ProductSPU.objects.filter(pk=skus[0].spu_id).update(category_node=child)
    # The SKU qualifies through its SPU category. Its linked legacy row has
    # neither source category nor generated SPU, so that filtered-out mapping
    # must not suppress the otherwise authorized SKU.
    ProductLegacyItem.objects.filter(pk=legacy[0].pk).update(generated_spu=None)
    response = _client(user).get("/api/internal/products/details/", {"category_id": category.id, "page_size": 20})
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 6
    assert {row["sku_code"] for row in response.json()["data"]["results"]} == {sku.sku_code for sku in skus}
    exported = _client(user).get("/api/internal/products/details/export/", {"category_id": category.id})
    text = exported.content.decode("utf-8-sig")
    assert skus[0].sku_code in text and legacy[0].legacy_sku_code not in text


@pytest.mark.django_db
def test_detail_export_keeps_exact_csv_bytes_and_reads_bounded_ordered_batches(monkeypatch):
    tenant, user, _, _ = _fixture("bounded-export", size=17)
    legacy = ProductLegacyItem.objects.filter(tenant=tenant).select_related(
        "category_node", "generated_spu", "generated_sku", "target_spu",
    ).order_by("-updated_at", "-id")
    linked_ids = set(legacy.exclude(generated_sku_id=None).values_list("generated_sku_id", flat=True))
    expected_rows = [views._product_detail_row_from_legacy(item) for item in legacy]
    expected_rows += [
        views._product_detail_row_from_sku(sku)
        for sku in ProductSKU.objects.filter(tenant=tenant).select_related("spu").order_by("-updated_at", "-id")
        if sku.id not in linked_ids
    ]
    headers = ["旧SPU编码", "旧SKU编码", "SPU编码", "SKU编码", "SKU商品名称", "SPU商品名称", "类目", "属性编码", "颜色编码", "规格", "采购价", "单位", "状态"]
    expected = views._product_csv_response("product-detail.csv", headers, (
        [row.get("legacy_spu_code"), row.get("legacy_sku_code"), row.get("spu_code"), row.get("sku_code"), row.get("sku_product_name") or row.get("product_name"), row.get("spu_product_name"), row.get("category_name"), row.get("attribute_code"), row.get("color_code"), row.get("specification"), row.get("purchase_price"), row.get("unit"), row.get("conversion_status_name") or row.get("sku_status_name")]
        for row in expected_rows
    ))
    original_iterator = views._iter_product_detail_export_rows
    monkeypatch.setattr(views, "_iter_product_detail_export_rows", lambda legacy, skus: original_iterator(legacy, skus, chunk_size=5))
    model_batches = []
    original_fetch = QuerySet._fetch_all

    def record_fetch(queryset):
        original_fetch(queryset)
        if queryset.model in (ProductLegacyItem, ProductSKU) and queryset._result_cache:
            assert queryset.query.is_sliced
            model_batches.append(len(queryset._result_cache))

    monkeypatch.setattr(QuerySet, "_fetch_all", record_fetch)
    with CaptureQueriesContext(connection) as queries:
        actual = _client(user).get("/api/internal/products/details/export/")
    assert actual.status_code == 200 and not actual.streaming
    assert actual.content == expected.content
    assert actual["Content-Disposition"] == expected["Content-Disposition"]
    assert actual["Content-Type"] == expected["Content-Type"]
    assert actual.content.startswith(b"\xef\xbb\xbf")
    assert "'=Formula SPU" in actual.content.decode("utf-8-sig")
    assert model_batches and max(model_batches) == 5
    input_queries = [query["sql"].upper() for query in queries if "FROM \"PRODUCTS_PRODUCTLEGACYITEM\"" in query["sql"].upper() or "FROM `PRODUCTS_PRODUCTLEGACYITEM`" in query["sql"].upper() or "FROM \"PRODUCTS_PRODUCTSKU\"" in query["sql"].upper() or "FROM `PRODUCTS_PRODUCTSKU`" in query["sql"].upper()]
    assert input_queries and all("LIMIT 5" in sql for sql in input_queries)
    parsed = list(csv.reader(io.StringIO(actual.content.decode("utf-8-sig"))))
    assert len(parsed) == 34  # 17 legacy + 16 standalone SKU + header.
