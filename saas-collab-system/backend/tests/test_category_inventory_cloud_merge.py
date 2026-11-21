from apps.sales_management.category_inventory import CategoryQuery, totals
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_category_ids_are_parsed_once_and_negative_one_is_allowed():
    query = CategoryQuery(data={"category_ids": "2,4", "category_id": "-1"})

    assert query.is_valid(), query.errors
    assert query.validated_data["category_ids"] == {2, 4}
    assert query.validated_data["category_id"] == -1


def test_blank_category_ids_are_empty_and_invalid_ids_rejected():
    blank = CategoryQuery(data={"category_ids": ""})
    assert blank.is_valid(), blank.errors
    assert blank.validated_data["category_ids"] == set()
    for invalid in ("0", "-1", "9223372036854775808"):
        query = CategoryQuery(data={"category_ids": invalid})
        assert not query.is_valid()


def test_unmapped_level_is_accepted_by_category_query():
    query = CategoryQuery(data={"level": "unmapped"})

    assert query.is_valid(), query.errors
    assert query.validated_data["level"] == "unmapped"


def test_totals_preserve_unknown_stock_and_sales_absence():
    assert totals({1, 2}, {1: 5}, {}) == {
        "available": None, "sales": None, "stock_coverage": 1, "sales_coverage": 0,
    }
    assert totals({1, 2}, {1: 5}, {1: 2}) == {
        "available": None, "sales": 2, "stock_coverage": 1, "sales_coverage": 1,
    }


def test_totals_keep_partial_sales_observation_and_stock_unknown():
    assert totals({1, 2}, {1: 5, 2: None}, {1: 2, 2: 0}) == {
        "available": None, "sales": 2, "stock_coverage": 1, "sales_coverage": 2,
    }


def _api_get(query, *, snapshots=(), products=(), categories=(), unmapped=([], 0, {})):
    from rest_framework.test import APIRequestFactory, force_authenticate
    from apps.sales_management.category_inventory import CategoryInventory

    actor = SimpleNamespace(tenant_id=1, pk=7, is_authenticated=True)
    country = SimpleNamespace(pk=3, country_code="US")
    catalog = MagicMock()
    catalog.filter.return_value = catalog
    catalog.order_by.return_value = catalog
    catalog.values.return_value = list(products)
    category_qs = MagicMock()
    category_qs.order_by.return_value = category_qs
    category_qs.values.return_value = list(categories)
    category_qs.keys.return_value = {row["id"] for row in categories}
    category_qs.__iter__.return_value = iter(categories)
    category_manager = MagicMock()
    category_manager.filter.return_value = category_qs
    category_manager.values.return_value = list(categories)

    with patch("apps.sales_management.category_inventory.domain.countries_for") as countries_for, \
         patch("apps.sales_management.category_inventory.domain.country_for", return_value=country), \
         patch("apps.sales_management.category_inventory.domain.skus_for", return_value=catalog), \
         patch("apps.sales_management.category_inventory.domain.permission_signature", return_value="sig"), \
         patch("apps.sales_management.category_inventory.ProductCategory.objects", category_manager), \
         patch("apps.sales_management.category_inventory._stock_context", return_value=(list(snapshots), {})), \
         patch("apps.sales_management.category_inventory.sales_facts", return_value=[]), \
         patch("apps.sales_management.abc_access.decorate_rows", return_value={}), \
         patch("apps.commerce.inventory_listing.linked_sku_ids", return_value=set()), \
         patch("apps.sales_management.category_inventory._unmapped", return_value=unmapped), \
         patch.object(CategoryInventory, "permission_classes", []):
        countries_for.return_value.values.return_value = []
        request = APIRequestFactory().get("/", query)
        force_authenticate(request, user=actor)
        response = CategoryInventory.as_view()(request)
    return response.data["data"], catalog


def _product(pk=10, category_id=1, spu_id=20):
    return {"id": pk, "sku_code": f"SKU-{pk}", "legacy_sku_code": "", "specification": "",
            "product_name": "Item", "image_url": "", "spu_id": spu_id, "spu__spu_code": "SPU",
            "spu__legacy_spu_code": "", "spu__product_name": "Product",
            "spu__category_node_id": category_id}


def test_category_intersection_applies_nonempty_and_empty_filters():
    categories = [{"id": 1, "parent_id": None, "name": "One"},
                  {"id": 2, "parent_id": None, "name": "Two"}]
    _, nonempty = _api_get({"country_id": 3, "category_id": 1, "category_ids": "1"},
                           products=[_product()], categories=categories)
    assert any(call.kwargs.get("spu__category_node_id__in") == {1}
               for call in nonempty.filter.call_args_list)
    _, empty = _api_get({"country_id": 3, "category_id": 1, "category_ids": "2"},
                        products=[], categories=categories)
    assert any(call.kwargs.get("spu__category_node_id__in") == set()
               for call in empty.filter.call_args_list)


def test_stocked_only_requires_known_positive_onhand_or_available():
    snapshots = [
        {"warehouse_id": 1, "warehouse__name": "W", "internal_sku_id": 10,
         "on_hand_qty": 2, "available_qty": 0, "on_hand_known": True, "available_known": True,
         "source_run_id": 1},
        {"warehouse_id": 2, "warehouse__name": "W2", "internal_sku_id": 11,
         "on_hand_qty": 9, "available_qty": 0, "on_hand_known": False, "available_known": True,
         "source_run_id": 2},
        {"warehouse_id": 3, "warehouse__name": "W3", "internal_sku_id": 12,
         "on_hand_qty": 0, "available_qty": 4, "on_hand_known": True, "available_known": True,
         "source_run_id": 3},
    ]
    _, catalog = _api_get({"country_id": 3, "stocked_only": "true"}, snapshots=snapshots)
    assert any(call.kwargs.get("pk__in") == {10, 12} for call in catalog.filter.call_args_list)


def test_quantity_known_flags_require_provided_fields_valid_batch_and_unique_alias():
    from apps.sales_management.category_inventory import _load_stock_facts

    base = {"site_code": "US", "warehouse_id": 1, "warehouse__name": "W", "seller_sku": "",
            "source_run_id": 9, "source_run__status": "success", "source_run__failed_count": 0,
            "internal_sku_id": 10, "on_hand_qty": 2, "available_qty": 0}
    unique = {**base, "id": 1, "internal_sku_id": 100, "source_sku": "unique", "provided_quantity_fields": ["on_hand_qty", "available_qty"]}
    no_on_hand_fact = {**base, "id": 2, "internal_sku_id": 101, "source_sku": "no-onhand", "provided_quantity_fields": ["available_qty"]}
    duplicate_a = {**base, "id": 3, "internal_sku_id": 102, "source_sku": "duplicate", "provided_quantity_fields": ["on_hand_qty", "available_qty"]}
    duplicate_b = {**duplicate_a, "id": 4}
    source = MagicMock()
    source.order_by.return_value.values.return_value = [unique, no_on_hand_fact, duplicate_a, duplicate_b]

    with patch("apps.sales_management.category_inventory._source", return_value=source):
        rows, inventory = _load_stock_facts(SimpleNamespace(), SimpleNamespace(), {})

    by_id = {row["id"]: row for row in rows}
    assert by_id[1]["on_hand_known"] and by_id[1]["available_known"]
    assert not by_id[2]["on_hand_known"] and by_id[2]["available_known"]
    assert not by_id[3]["on_hand_known"] and not by_id[4]["available_known"]
    assert inventory[100] == 0 and inventory[101] == 0 and inventory[102] is None


def test_abc_filter_branch_and_warehouse_rows_include_id_and_pagination():
    products = [_product()]
    categories = [{"id": 1, "parent_id": None, "name": "One"}]
    with patch("apps.sales_management.abc_access.filter_skus") as filter_skus:
        _api_get({"country_id": 3, "level": "spu", "abc_grade": "A"}, products=products, categories=categories)
        assert filter_skus.call_args.kwargs["grouped"] is True
        filter_skus.reset_mock()
        _api_get({"country_id": 3, "level": "sku", "spu_id": 20, "abc_grade": "A"}, products=products, categories=categories)
        assert filter_skus.call_args.kwargs["grouped"] is True
        filter_skus.reset_mock()
        _api_get({"country_id": 3, "level": "sku", "sku_id": 10, "abc_grade": "A"}, products=products, categories=categories)
        filter_skus.assert_not_called()

    snapshots = [{"warehouse_id": 8, "warehouse__name": "Main", "internal_sku_id": 10,
                  "available_qty": 5, "available_known": True, "source_run_id": 9}]
    data, _ = _api_get({"country_id": 3, "level": "warehouses", "sku_id": 10,
                        "offset": 1}, snapshots=snapshots, products=products, categories=categories)
    assert data["results"] == [] and data["offset"] == 1 and data["limit"] == 20
    data, _ = _api_get({"country_id": 3, "level": "warehouses", "sku_id": 10},
                       snapshots=snapshots, products=products, categories=categories)
    assert data["results"] == [{"id": 8, "name": "Main", "available": 5}]


def test_category_sales_complete_and_synthetic_unmapped_result():
    products = [_product(10), _product(11)]
    categories = [{"id": 1, "parent_id": None, "name": "One"}]
    data, _ = _api_get({"country_id": 3}, products=products, categories=categories,
                       unmapped=([], 2, {"sku_count": 2, "available": 4, "on_hand": 5}))
    category = next(row for row in data["results"] if row["id"] == 1)
    assert category["sales_complete"] is False
    synthetic = next(row for row in data["results"] if row["id"] == -1)
    assert synthetic["sales"] is None and synthetic["sku_count"] == 2
