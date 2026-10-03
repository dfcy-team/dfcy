from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.integrations.feishu_reports import _unit, build_report, report_csv
from apps.integrations import feishu_reports
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from tests.test_sales_management import create_order, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("dataset,key,unit", [
    ("sales", "order_count", "单"), ("sales", "valid_order_count", "单"),
    ("sales_skus", "units_sold", "件"), ("inventory", "on_hand", "件"),
    ("inventory", "available", "件"), ("refunds", "case_count", "单"),
    ("refunds", "unlinked_count", "单"), ("finance", "transaction_count", "笔"),
    ("finance", "unmatched_count", "笔"), ("finance", "unknown_count", "笔"),
    ("inventory", "sku_count", "个"), ("inventory_value", "valued_count", "个"),
    ("inventory_value", "missing_cost_count", "个"), ("inventory_value", "zero_cost_count", "个"),
    ("sales_skus", "unmapped_count", "条"), ("inventory", "unmapped_count", "个"),
])
def test_units_are_explicit_and_money_never_defaults_to_currency(dataset, key, unit):
    assert _unit(dataset, key, {}) == unit
    assert _unit("sales", "gross_sales", {"currency": None}) == "未知币种"
    assert _unit("finance", "signed_amount", {"currency": "USD"}) == "USD"


def test_sales_empty_window_reports_latest_order_in_recipient_scope():
    tenant, platform, allowed_store, _ = create_scope("feishu-freshness-authorized", "PHP", "PH")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="freshness-hidden", name="hidden", country_code="TH", currency="THB", timezone="Asia/Bangkok",
    )
    old_order = create_order(tenant, allowed_store, "freshness-old")
    recent_hidden_order = create_order(tenant, hidden_store, "freshness-hidden")
    type(old_order).objects.filter(pk=old_order.pk).update(business_date="2026-09-20")
    type(old_order).objects.filter(pk=recent_hidden_order.pk).update(business_date="2026-09-30")
    recipient = user_for(tenant, "freshness-recipient")
    grant(recipient, "reports.view", DataScope.ScopeType.ALL)
    grant(recipient, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [allowed_store.pk]})

    report = build_report(
        SimpleNamespace(config={"report_type": "sales", "filters": {"date_from": "2026-10-02", "date_to": "2026-10-02"}}), recipient,
    )
    section = report["sections"][0]
    assert section["status"] == "no_data"
    assert section["data_range"] == "2026-10-02 至 2026-10-02"
    assert section["source_latest_date"] == "2026-09-20"
    assert section["data_range"] in report["summary"]
    assert "当前权限下库内最新订单日期为2026-09-20" in report["summary"]
    assert "2026-09-30" not in report["summary"]
    csv_text = report_csv(report).decode("utf-8-sig")
    assert "最新业务日期" in csv_text and "2026-09-20" in csv_text


def test_empty_authorized_sales_source_is_distinct_from_stale_data(monkeypatch):
    monkeypatch.setattr(feishu_reports, "latest_sales_business_date", lambda *_: None)
    section = {"dataset": "sales", "title": "销售摘要", "status": "no_data", "data_range": "2026-10-02 至 2026-10-02", "rows": [], "truncated": False}
    assert "当前权限范围内尚无已入库订单" in feishu_reports._summary(section)


def test_csv_has_independent_unit_column_and_only_metrics():
    report = {"title": "Sales", "generated_at": "now", "sections": [{
        "dataset": "sales", "title": "Sales", "status": "available", "data_range": "range", "as_of": "now", "note": "note",
        "rows": [{"country": "US", "country_code": "US", "currency": "", "order_count": 2, "gross_sales": Decimal("3.25")}],
    }]}
    text = report_csv(report).decode("utf-8-sig")
    assert "单位" in text and "order_count,2,单" in text and "gross_sales,3.25,未知币种" in text
    assert "country_code" not in text and "country,US" not in text
