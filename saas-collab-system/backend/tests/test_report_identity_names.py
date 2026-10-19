import csv
import io

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commerce.models import SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from apps.reports.models import ReportExportRequest
from tests.test_report_revision import _config, _report_access, _second_store
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


def test_store_choices_before_query_are_scoped_searchable_and_do_not_reveal_foreign_stores():
    tenant, _, visible, _ = create_scope("identity-options")
    hidden = _second_store(tenant, "hidden-identity")
    foreign, _, foreign_store, _ = create_scope("identity-foreign")
    for scope, store, suffix in ((tenant, visible, "visible"), (tenant, hidden, "hidden"), (foreign, foreign_store, "foreign")):
        create_order(scope, store, f"identity-{suffix}")
    visible.name = "菲律宾运营店"
    visible.save(update_fields=["name"])
    user = user_for(tenant, "identity-options-viewer")
    grant(user, "reports.view")
    grant(user, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(visible.pk)]})
    client = client_for(user)
    response = client.post("/api/report/filter-options/", {"dataset": "sales", "search": "运营"}, format="json")
    assert response.status_code == 200
    options = response.data["data"]["options"]
    assert [row["value"] for row in options] == [str(visible.pk)]
    assert visible.name in options[0]["label"] and visible.code in options[0]["label"]
    assert client.post("/api/report/filter-options/", {"dataset": "sales", "search": "hidden"}, format="json").data["data"]["options"] == []


def test_store_choices_require_current_dataset_access_and_validate_payload():
    tenant, _, _, _ = create_scope("identity-denied")
    user = user_for(tenant, "identity-denied")
    grant(user, "reports.view")
    client = client_for(user)
    assert client.post("/api/report/filter-options/", {"dataset": "sales"}, format="json").status_code == 403
    assert client.post("/api/report/filter-options/", {"dataset": "inventory"}, format="json").status_code == 400
    assert client.post("/api/report/filter-options/", {"dataset": []}, format="json").status_code == 400
    assert client.post("/api/report/filter-options/", {"dataset": "sales", "search": "a" * 101}, format="json").status_code == 400


def test_store_choices_are_bounded_and_can_find_names_after_first_page():
    tenant, platform, store, _ = create_scope("identity-bounded")
    user = user_for(tenant, "identity-bounded")
    _report_access(user, "sales_management.view")
    # No fact or scope expansion: only stores with authorized report evidence are choices.
    for index in range(101):
        other = StoreMaster.objects.create(tenant=tenant, platform=platform, code=f"identity-{index}", name=f"店铺{index:03}", country_code="PH", currency="PHP", timezone="Asia/Manila")
        create_order(tenant, other, f"identity-bound-{index}")
    client = client_for(user)
    result = client.post("/api/report/filter-options/", {"dataset": "sales"}, format="json").data["data"]
    assert len(result["options"]) == 100 and result["has_more"]
    result = client.post("/api/report/filter-options/", {"dataset": "sales", "search": "店铺100"}, format="json").data["data"]
    assert len(result["options"]) == 1 and not result["has_more"]


def test_product_names_do_not_change_groups_or_add_per_row_queries():
    tenant, _, store, _ = create_scope("identity-skus")
    user = user_for(tenant, "identity-skus")
    _report_access(user, "sales_management.view")
    first = create_order(tenant, store, "identity-first")
    SalesOrderItem.objects.filter(sales_order=first).update(seller_sku="same-code", item_name_snapshot="名称甲")
    second = create_order(tenant, store, "identity-second")
    SalesOrderItem.objects.filter(sales_order=second).update(seller_sku="same-code", item_name_snapshot="名称乙")
    client = client_for(user)
    config = _config("sales_skus", ["store_id", "sku"], ["units_sold"])
    cache.clear()
    with CaptureQueriesContext(connection) as one:
        data = client.post("/api/report/query/", config, format="json").data["data"]
    assert len(data["rows"]) == 1 and data["rows"][0]["units_sold"] == 4
    assert data["identity_names"]["sku"]["same-code"] == "名称存在差异，查看明细"
    for index in range(5):
        order = create_order(tenant, store, f"identity-extra-{index}")
        SalesOrderItem.objects.filter(sales_order=order).update(item_name_snapshot=f"商品{index}")
    cache.clear()
    with CaptureQueriesContext(connection) as many:
        data = client.post("/api/report/query/", config, format="json").data["data"]
    assert len(many) <= len(one) + 1
    assert "商品0" in data["dimension_labels"]["sku"]["SKU-identity-extra-0"]


def test_csv_keeps_codes_and_includes_store_and_product_names_safely(tmp_path, settings):
    settings.REPORT_EXPORT_ROOT = str(tmp_path)
    tenant, _, store, _ = create_scope("identity-csv")
    store.name = "=危险店铺名称"
    store.save(update_fields=["name"])
    order = create_order(tenant, store, "identity-csv")
    SalesOrderItem.objects.filter(sales_order=order).update(item_name_snapshot="兔毛毯子")
    user = user_for(tenant, "identity-csv")
    _report_access(user, "sales_management.view", "sales_management.export", "reports.export")
    response = client_for(user).post("/api/report/exports/", {"report_type": "self_service", "filters": {"config": _config("sales_skus", ["store_id", "sku"], ["units_sold"])}}, format="json")
    assert response.status_code == 201
    export = ReportExportRequest.objects.get(pk=response.data["data"]["id"])
    rows = list(csv.reader(io.StringIO((tmp_path / export.storage_key).read_text(encoding="utf-8-sig"))))
    assert rows[0][:4] == ["店铺编号", "店铺名称", "平台 SKU", "商品名称"]
    assert rows[1][:4] == [str(store.pk), "'=危险店铺名称", "SKU-identity-csv", "兔毛毯子"]


def test_quality_conflicting_store_refs_cannot_resolve_hidden_store_name():
    from apps.integrations.models import APISyncTask, APISyncLog, APIDataQualityCheck
    tenant, _, visible, _ = create_scope("identity-conflict")
    hidden = _second_store(tenant, "secret-hidden-identity")
    task = APISyncTask.objects.create(tenant=tenant, platform="shopee", sync_type="sales_order",
        config={"store_id": str(hidden.pk), "store_code": visible.code})
    log = APISyncLog.objects.create(tenant=tenant, task=task, status="failed")
    issue = APIDataQualityCheck.objects.create(tenant=tenant, sync_log=log, check_type="conflict", status="failed")
    user = user_for(tenant, "identity-conflict")
    grant(user, "sales_management.data_quality.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(visible.pk)]})
    response = client_for(user).get("/api/internal/commerce/quality/")
    assert response.status_code == 200
    rows = response.data["data"]["issues"]
    assert [row["id"] for row in rows] == [issue.pk]
    assert rows[0]["store_name"] == visible.name
    assert rows[0]["store_code"] == visible.code
    assert hidden.name not in str(rows)


def test_advertising_store_options_include_authorized_historical_only_store():
    from datetime import timedelta
    from django.utils import timezone
    from apps.integrations.models import ShopeeAdvertisingRecord
    from tests.test_sync_capability_gate import make_job
    from tests.test_sales_management import create_run
    job, authorization = make_job()
    user, store = job.integration_config.created_by, authorization.store
    grant(user, "reports.view")
    grant(user, "analytics.view", DataScope.ScopeType.CUSTOM,
        {"analytics_dimensions": [{"store_id": str(store.pk), "platform": "shopee", "country": "PH"}]})
    run = create_run(job.tenant, "sales_order", "identity-historical-advertising")
    ShopeeAdvertisingRecord.objects.create(tenant=job.tenant, store=store, source_run=run, kind="shop_daily",
        record_key="identity-historical-shop", report_date=timezone.localdate() - timedelta(days=90), currency="PHP",
        report_timezone="Asia/Manila", dimensions={"store_id": str(store.pk), "platform": "shopee", "country": "PH"}, data={"expense": "1"})
    response = client_for(user).post("/api/report/filter-options/", {"dataset": "advertising", "search": store.name}, format="json")
    assert response.status_code == 200
    assert [row["value"] for row in response.data["data"]["options"]] == [str(store.pk)]
