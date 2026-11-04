from datetime import datetime, timezone
from decimal import Decimal
from contextlib import nullcontext
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings

from rest_framework.exceptions import PermissionDenied

from apps.sales_management.sales_operations import (
    _add_ad_metric,
    _diagnosis_evidence,
    _unique_sku_candidates,
    _wms_snapshot_step,
)


def test_ad_metrics_keep_missing_and_invalid_values_null_and_parse_numeric_strings():
    bucket = {"total": Decimal("0"), "count": 0}
    _add_ad_metric(bucket, "total", "12.5")
    _add_ad_metric(bucket, "total", 2)
    negative = {"total": Decimal("0"), "count": 0}
    _add_ad_metric(negative, "total", "-1")
    _add_ad_metric(negative, "total", "NaN")
    assert bucket == {"total": Decimal("14.5"), "count": 2}
    assert negative == {"total": Decimal("0"), "count": 0}


def test_ambiguous_platform_sku_mapping_is_not_resolved():
    key = (1, 2, "product", "variant")
    assert _unique_sku_candidates({key: {11, 12}, (1, 3, "product", "variant"): {13}}) == {
        (1, 3, "product", "variant"): 13,
    }


def test_wms_snapshot_does_not_treat_unprovided_quantity_as_zero_and_keeps_location_time():
    base = {
        "site_code": "PH", "warehouse__name": "Manila", "source_sku": "A-1",
        "available_qty": 0, "provided_quantity_fields": [],
        "snapshot_at_utc": datetime(2026, 11, 2, 16, tzinfo=timezone.utc),
    }
    step = _wms_snapshot_step(base)
    assert step["value"] is None and step["status"] == "missing"
    assert "Manila" in step["label"] and step["snapshot_at"] == "2026-11-02T16:00:00+00:00"


def test_ad_permission_denial_leaves_shop_evidence_missing_and_does_not_leak_internal_keys():
    tenant = object()
    row = {
        "store_id": 8, "currency": "PHP", "product_id": "p1", "_platform_id": 1,
        "_variant_count": 2, "_platform_variant_id": None,
        "diagnosis": {"steps": [], "missing": ["库存"]},
    }
    request = SimpleNamespace(user=SimpleNamespace(tenant=tenant))
    with patch("apps.reports.advertising_dataset.advertising_queryset", side_effect=PermissionDenied), \
         patch("django.db.transaction.atomic", return_value=nullcontext()):
        _diagnosis_evidence(request, {"date_to": datetime(2026, 11, 2).date()}, [row])
    assert row["diagnosis"]["shop_ad_data"] is False
    assert not {"_platform_id", "_variant_count", "_platform_variant_id"} & row.keys()
    assert row["diagnosis"]["steps"][-1]["status"] == "missing"


def test_platform_mapping_query_uses_full_product_variant_and_store_identity():
    class AdQuery:
        def filter(self, **kwargs):
            return self

        def values(self, *args):
            return []

    row = {
        "store_id": 22, "currency": "PHP", "product_id": "product-A", "_platform_id": 3,
        "_variant_count": 1, "_platform_variant_id": "variant-X",
        "diagnosis": {"steps": [], "missing": ["库存"]},
    }
    request = SimpleNamespace(user=SimpleNamespace(tenant=object()))
    expected = {
        "tenant": request.user.tenant, "store_id__in": {22}, "platform_id__in": {3},
        "platform_product_id__in": {"product-A"}, "platform_variant_id__in": {"variant-X"},
        "internal_sku__isnull": False, "internal_sku__tenant": request.user.tenant,
    }
    with patch("apps.reports.advertising_dataset.advertising_queryset", return_value=AdQuery()), \
         patch("django.db.transaction.atomic", return_value=nullcontext()), \
         patch("apps.listings.models.PlatformProductDetail.objects.filter", return_value=AdQuery()) as query:
        _diagnosis_evidence(request, {"date_to": datetime(2026, 11, 2).date()}, [row])
    query.assert_called_once_with(**expected)


def test_wms_success_path_filters_at_business_day_cutoff_and_emits_each_snapshot_time():
    class AdQuery:
        def filter(self, **kwargs):
            return self

        def values(self, *args):
            return []

    class InventorySource:
        def filter(self, **kwargs):
            self.filters = kwargs
            return self

    class Latest:
        def filter(self, **kwargs):
            self.filters = kwargs
            return self

        def select_related(self, *args):
            return self

        def values(self, *args):
            return [{
                "internal_sku_id": 91, "source_sku": "SRC-1", "warehouse_id": 12,
                "warehouse__name": "Cebu", "site_code": "PH", "available_qty": 7,
                "provided_quantity_fields": ["available_qty"],
                "snapshot_at_utc": datetime(2026, 11, 2, 8, 15, tzinfo=timezone.utc),
            }]

    row = {
        "store_id": 22, "currency": "PHP", "product_id": "product-A", "_platform_id": 3,
        "_variant_count": 1, "_platform_variant_id": "variant-X",
        "diagnosis": {"steps": [], "missing": ["库存"]},
    }
    request = SimpleNamespace(user=SimpleNamespace(tenant=object()))
    source = InventorySource()
    mapped_row = {"platform_id": 3, "store_id": 22, "platform_product_id": "product-A", "platform_variant_id": "variant-X", "internal_sku_id": 91}
    with patch("apps.reports.advertising_dataset.advertising_queryset", return_value=AdQuery()), \
         patch("django.db.transaction.atomic", return_value=nullcontext()), \
         patch("apps.listings.models.PlatformProductDetail.objects.filter", return_value=AdQuery()) as details_query, \
         patch("apps.sales_management.views._inventory_source", return_value=source), \
         patch("apps.sales_management.views._inventory_latest", return_value=Latest()):
        details_query.return_value.values = lambda *args: [mapped_row]
        _diagnosis_evidence(request, {"date_to": datetime(2026, 11, 2).date()}, [row])
    assert source.filters == {"snapshot_at_utc__lt": datetime(2026, 11, 3, 0, tzinfo=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)).astimezone(timezone.utc)}
    expected_cutoff = datetime(2026, 11, 3, 0, tzinfo=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)).astimezone(timezone.utc)
    assert source.filters["snapshot_at_utc__lt"] == expected_cutoff
    step = row["diagnosis"]["steps"][-1]
    assert step["value"] == 7 and "Cebu" in step["label"]
    assert step["snapshot_at"] == "2026-11-02T08:15:00+00:00"


def test_wms_latest_identity_is_ranked_before_filtering_sku_mapping_changes():
    # Run the actual diagnosis caller against a SQLite-backed inventory adapter.
    # The adapter applies source filters before its real ROW_NUMBER query, so
    # moving the SKU filter back before _inventory_latest reproduces the bug.
    class AdQuery:
        def filter(self, **kwargs):
            return self

        def values(self, *args):
            return []

    inventory_rows = [
        ("PH", 12, "SRC-1", 91, "2026-11-02T10:00:00Z", 9),
        ("PH", 12, "SRC-1", 92, "2026-11-02T11:00:00Z", 0),
        ("PH", 13, "SRC-2", 91, "2026-11-02T10:00:00Z", 9),
        ("PH", 13, "SRC-2", None, "2026-11-02T11:00:00Z", 0),
    ]

    class InventorySource:
        def __init__(self):
            self.filters = {}

        def filter(self, **kwargs):
            self.filters.update(kwargs)
            return self

    class Latest:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, **kwargs):
            if "internal_sku_id__in" in kwargs:
                self.rows = [r for r in self.rows if r["internal_sku_id"] in kwargs["internal_sku_id__in"]]
            return self

        def select_related(self, *args):
            return self

        def values(self, *args):
            return self.rows

    source = InventorySource()

    def sqlite_inventory_latest(source_query):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE inventory (site_code TEXT, warehouse_id INTEGER, source_sku TEXT, internal_sku_id INTEGER, snapshot_at TEXT, available_qty INTEGER)")
        eligible = inventory_rows
        if "internal_sku_id__in" in source_query.filters:
            eligible = [r for r in eligible if r[3] in source_query.filters["internal_sku_id__in"]]
        cutoff = source_query.filters["snapshot_at_utc__lt"]
        eligible = [r for r in eligible if datetime.fromisoformat(r[4].replace("Z", "+00:00")) < cutoff]
        db.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?)", eligible)
        ranked = db.execute("""
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY site_code, warehouse_id, source_sku
                    ORDER BY snapshot_at DESC
                ) AS rank
                FROM inventory
            )
            SELECT site_code, warehouse_id, source_sku, internal_sku_id, snapshot_at, available_qty
            FROM ranked WHERE rank = 1
        """).fetchall()
        db.close()
        return Latest([{
            "site_code": r[0], "warehouse_id": r[1], "source_sku": r[2],
            "internal_sku_id": r[3], "snapshot_at_utc": datetime.fromisoformat(r[4].replace("Z", "+00:00")),
            "available_qty": r[5], "warehouse__name": "Manila",
            "provided_quantity_fields": ["available_qty"],
        } for r in ranked])

    row = {
        "store_id": 22, "currency": "PHP", "product_id": "product-A", "_platform_id": 3,
        "_variant_count": 1, "_platform_variant_id": "variant-X",
        "diagnosis": {"steps": [], "missing": ["库存"]},
    }
    request = SimpleNamespace(user=SimpleNamespace(tenant=object()))
    mapped_row = {"platform_id": 3, "store_id": 22, "platform_product_id": "product-A", "platform_variant_id": "variant-X", "internal_sku_id": 91}
    with patch("apps.reports.advertising_dataset.advertising_queryset", return_value=AdQuery()), \
         patch("django.db.transaction.atomic", return_value=nullcontext()), \
         patch("apps.listings.models.PlatformProductDetail.objects.filter", return_value=AdQuery()) as details_query, \
         patch("apps.sales_management.views._inventory_source", return_value=source), \
         patch("apps.sales_management.views._inventory_latest", side_effect=sqlite_inventory_latest):
        details_query.return_value.values = lambda *args: [mapped_row]
        _diagnosis_evidence(request, {"date_to": datetime(2026, 11, 2).date()}, [row])
    assert source.filters == {"snapshot_at_utc__lt": datetime(2026, 11, 3, 0, tzinfo=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)).astimezone(timezone.utc)}
    assert row["diagnosis"]["steps"][-1]["status"] == "missing"
    assert not any("SRC-1" in step["label"] or "SRC-2" in step["label"] for step in row["diagnosis"]["steps"])
    old_source = InventorySource().filter(internal_sku_id__in={91}, snapshot_at_utc__lt=source.filters["snapshot_at_utc__lt"])
    old_ranked = sqlite_inventory_latest(old_source).filter(internal_sku_id__in={91}).values()
    assert [fact["available_qty"] for fact in old_ranked] == [9, 9]

