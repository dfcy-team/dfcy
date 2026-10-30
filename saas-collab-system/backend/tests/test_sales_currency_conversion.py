from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.masterdata.models import CountrySiteMaster
from apps.sales_management.currency_conversion import convert_sales_payload
from apps.sales_management.cny_summary import cny_summary
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for


@pytest.mark.django_db
def test_cny_summary_keeps_sales_scope_and_only_comparable_roi_groups():
    tenant, _, _, _ = create_scope("cny-summary")
    CountrySiteMaster.objects.create(tenant=tenant, code="ph", name="PH", country_code="PH", currency="PHP",
                                     cny_exchange_rate=Decimal("10"), exchange_rate_date=date(2026, 9, 17))
    CountrySiteMaster.objects.create(tenant=tenant, code="th", name="TH", country_code="TH", currency="THB",
                                     cny_exchange_rate=Decimal("5"), exchange_rate_date=date(2026, 9, 18))
    request = SimpleNamespace(user=SimpleNamespace(tenant=tenant))
    result = cny_summary(request, [
        {"currency": "PHP", "sales_amount": "100", "ad_sales_amount": "50", "ad_spend": "10", "roi": "5", "ad_status": "partial"},
        {"currency": "THB", "sales_amount": "50", "ad_sales_amount": None, "ad_spend": "5"},
        {"currency": "XYZ", "sales_amount": "99", "ad_spend": "8"},
    ], "sales_amount", "ad_sales_amount")
    assert result["sales_amount"] == "20"
    assert result["ad_spend"] == "2"
    assert result["roi_sales_amount"] == "5"
    assert result["roi"] == "5"
    assert result["excluded_currencies"] == ["XYZ"]
    assert result["rate_dates"] == ["2026-09-17", "2026-09-18"]
    assert result["ad_partial"] is True
    assert result["missing_rate_currencies"] == ["XYZ"]
    assert result["incomparable_roi_currencies"] == ["THB"]


@pytest.mark.django_db
def test_cny_summary_returns_null_when_no_valid_rate_and_counts_zero_spend_roi_scope():
    tenant, _, _, _ = create_scope("cny-summary-null")
    CountrySiteMaster.objects.create(tenant=tenant, code="ph", name="PH", country_code="PH", currency="PHP",
                                     cny_exchange_rate=Decimal("10"), exchange_rate_date=date(2026, 9, 17))
    request = SimpleNamespace(user=SimpleNamespace(tenant=tenant))
    unavailable = cny_summary(request, [{"currency": "XXX", "sales_amount": "4", "ad_spend": "0"}], "sales_amount")
    assert unavailable["sales_amount"] is None
    assert unavailable["ad_spend"] is None
    assert unavailable["coverage"] == {"sales_currency_count": 0, "ad_spend_currency_count": 0}
    zero_expense = cny_summary(request, [{"currency": "PHP", "sales_amount": "20", "ad_sales_amount": "20", "ad_spend": "0", "roi": None}], "sales_amount", "ad_sales_amount")
    assert zero_expense["roi_sales_amount"] == "2"
    assert zero_expense["roi_ad_spend"] == "0"
    assert zero_expense["roi"] is None


@pytest.mark.django_db
def test_converts_rows_and_merges_currency_groups_to_cny():
    tenant, _, _, _ = create_scope("currency-conversion")
    CountrySiteMaster.objects.create(tenant=tenant, code="ph", name="PH", country_code="PH", currency="PHP",
                                     cny_exchange_rate=Decimal("10"), exchange_rate_date=date(2026, 9, 17))
    CountrySiteMaster.objects.create(tenant=tenant, code="th", name="TH", country_code="TH", currency="THB",
                                     cny_exchange_rate=Decimal("5"), exchange_rate_date=date(2026, 9, 17))
    request = SimpleNamespace(query_params={"currency_basis": "CNY"}, user=SimpleNamespace(tenant=tenant))
    payload = {
        "results": [
            {"currency": "PHP", "gross_sales": "100", "order_count": 1},
            {"currency": "THB", "gross_sales": "50", "order_count": 2},
        ],
        "currency_groups": [
            {"currency": "PHP", "metrics": [{"code": "gross_sales", "value": "100", "unit": "PHP"}, {"code": "order_count", "value": "1", "unit": "orders"}]},
            {"currency": "THB", "metrics": [{"code": "gross_sales", "value": "50", "unit": "THB"}, {"code": "order_count", "value": "2", "unit": "orders"}]},
        ],
    }

    result = convert_sales_payload(request, payload)

    assert [row["gross_sales"] for row in result["results"]] == ["10", "10"]
    assert all(row["currency"] == "CNY" for row in result["results"])
    assert result["currency_groups"][0]["metrics"] == [
        {"code": "gross_sales", "value": "20", "unit": "CNY"},
        {"code": "order_count", "value": "3", "unit": "orders"},
    ]
    assert result["currency_conversion"]["rate_dates"] == ["2026-09-17"]


@pytest.mark.django_db
def test_converts_order_detail_and_nested_lines_to_cny():
    tenant, _, _, _ = create_scope("currency-conversion-detail")
    CountrySiteMaster.objects.create(
        tenant=tenant, code="ph", name="PH", country_code="PH", currency="PHP",
        cny_exchange_rate=Decimal("10"), exchange_rate_date=date(2026, 9, 17),
    )
    request = SimpleNamespace(query_params={"currency_basis": "CNY"}, user=SimpleNamespace(tenant=tenant))

    result = convert_sales_payload(request, {
        "currency": "PHP", "order_total_amount": "250",
        "items": [{"currency": "PHP", "line_total_amount": "100"}],
    })

    assert result["source_currency"] == "PHP"
    assert result["currency"] == "CNY"
    assert result["order_total_amount"] == "25"
    assert result["source_amounts"]["order_total_amount"] == "250"
    assert result["items"][0]["line_total_amount"] == "10"
    assert result["items"][0]["source_amounts"]["line_total_amount"] == "100"


@pytest.mark.django_db
def test_overview_endpoint_accepts_automatic_cny_basis():
    tenant, _, store, _ = create_scope("currency-conversion-api")
    create_order(tenant, store, "currency-conversion-api", "100")
    CountrySiteMaster.objects.create(
        tenant=tenant, code="ph", name="PH", country_code="PH", currency="PHP",
        cny_exchange_rate=Decimal("10"), exchange_rate_date=date(2026, 9, 17),
    )
    viewer = user_for(tenant, "currency-conversion-api-viewer")
    grant(viewer, "sales_management.view")

    response = client_for(viewer).get("/api/internal/commerce/overview/", {"currency_basis": "CNY"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["currency"] == "CNY"
    assert data["currency_conversion"]["target"] == "CNY"
    assert data["order_daily"][0]["total_sales"] == "10"
