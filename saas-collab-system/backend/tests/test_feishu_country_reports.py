from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.integrations.feishu_reports import build_report, report_csv
from apps.integrations import feishu_reports
from apps.masterdata.models import CountrySiteMaster, StoreMaster
from apps.permissions.models import DataScope
from tests.test_sales_management import create_order, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


def test_feishu_sales_groups_by_country_currency_and_live_recipient_scope():
    tenant, platform, store_ph, _ = create_scope("feishu-country-ph", "PHP", "PH")
    store_th = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="feishu-country-th", name="Thailand",
        country_code="TH", currency="PHP", timezone="Asia/Bangkok",
    )
    CountrySiteMaster.objects.create(tenant=tenant, code="ph", name="东南亚", country_code="PH")
    CountrySiteMaster.objects.create(tenant=tenant, code="th", name="东南亚", country_code="TH")
    foreign_tenant, _, _, _ = create_scope("feishu-country-foreign", "USD", "PH")
    CountrySiteMaster.objects.create(tenant=foreign_tenant, code="ph-foreign", name="跨租户泄漏名", country_code="PH")
    create_order(tenant, store_ph, "country-ph")
    create_order(tenant, store_th, "country-th")

    recipient = user_for(tenant, "feishu-country-recipient")
    grant(recipient, "reports.view", DataScope.ScopeType.ALL)
    grant(recipient, "sales_management.view", DataScope.ScopeType.ALL)
    report = build_report(
        SimpleNamespace(config={"report_type": "sales", "filters": {"date_from": "2026-08-17", "date_to": "2026-08-17"}}),
        recipient,
    )
    section = report["sections"][0]
    assert section["rows"] == [
        {"country": "东南亚 (PH)", "country_code": "PH", "currency": "PHP", "order_count": 1, "valid_order_count": 1, "gross_sales": Decimal("100.0000")},
        {"country": "东南亚 (TH)", "country_code": "TH", "currency": "PHP", "order_count": 1, "valid_order_count": 1, "gross_sales": Decimal("100.0000")},
    ]
    assert "东南亚 (PH) PHP" in report["summary"]
    assert "东南亚 (TH) PHP" in report["summary"]
    assert "跨租户泄漏名" not in report["summary"]
    csv_text = report_csv(report).decode("utf-8-sig")
    assert "国家,币种,指标" in csv_text
    assert "东南亚 (PH),PHP,gross_sales" in csv_text
    assert "东南亚 (PH),PHP,country_code" not in csv_text
    assert "东南亚 (PH),PHP,currency" not in csv_text

    restricted = user_for(tenant, "feishu-country-restricted-recipient")
    grant(restricted, "reports.view", DataScope.ScopeType.ALL)
    grant(restricted, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [store_ph.id]})
    restricted_report = build_report(
        SimpleNamespace(config={"report_type": "sales", "filters": {"date_from": "2026-08-17", "date_to": "2026-08-17"}}),
        restricted,
    )
    assert [row["country_code"] for row in restricted_report["sections"][0]["rows"]] == ["PH"]


@pytest.mark.parametrize("dataset", ["sales", "sales_skus", "refunds", "finance", "inventory", "inventory_value"])
def test_each_feishu_dataset_requests_its_scoped_country_dimension(monkeypatch, dataset):
    captured = {}

    def fake_query(_request, raw, **_kwargs):
        captured.update(raw)
        dimension = "warehouse_country" if dataset.startswith("inventory") else "country"
        return {"config": {"filters": raw["filters"]}, "rows": [], "dimension_labels": {dimension: {}}}

    monkeypatch.setattr(feishu_reports, "query_dataset", fake_query)
    feishu_reports._query(object(), dataset, {"date_from": "2026-08-17", "date_to": "2026-08-17"})
    expected = "warehouse_country" if dataset.startswith("inventory") else "country"
    assert expected in captured["dimensions"]
    if dataset in feishu_reports.MONEY_DATASETS:
        assert "currency" in captured["dimensions"]


@pytest.mark.parametrize("dataset", list(feishu_reports.METRICS))
def test_aggregates_keep_country_codes_separate_and_preserve_unknown(dataset):
    money = dataset in feishu_reports.MONEY_DATASETS
    first_metric = feishu_reports.METRICS[dataset][0]
    rows = [
        {"country_code": "PH", "country_name": "Same", "currency": "PHP", first_metric: 2},
        {"country_code": "TH", "country_name": "Same", "currency": "PHP", first_metric: 3},
        {"country_code": "", "country_name": "国家未设置", "currency": "PHP", first_metric: 4},
    ]
    if money:
        rows.append({"country_code": "PH", "country_name": "Same", "currency": "USD", first_metric: 5})
    result = feishu_reports._sum_rows(dataset, rows)
    assert {row["country_code"] for row in result} == {"PH", "TH", ""}
    if money:
        assert {row["currency"] for row in result} == {"PHP", "USD"}
    assert sum(row[first_metric] for row in result) == (14 if money else 9)


def test_csv_keeps_country_and_currency_columns_and_formula_protection():
    report = {"title": "T", "generated_at": "now", "sections": [{
        "dataset": "finance", "title": "流水", "status": "available", "data_range": "range", "as_of": "now",
        "note": "=1+1", "rows": [{"country": "United States (US)", "country_code": "US", "currency": "USD", "transaction_count": 1, "signed_amount": Decimal("4.00"), "unknown_count": 0}],
    }]}
    text = report_csv(report).decode("utf-8-sig")
    assert "United States (US),USD,transaction_count,1" in text
    assert "United States (US),USD,country_code" not in text
    assert "'=1+1" in text
