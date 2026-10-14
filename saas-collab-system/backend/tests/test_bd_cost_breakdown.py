"""Synthetic BD cost facts only; run with settlement_test in an isolated test DB."""

import csv
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser
from apps.influencers.attribution import BD_COST_BASIS, _RateResolver, build_bd_performance
from apps.influencers.models import AffiliateOrderSnapshot, BdSampleAttributionSnapshot, ExchangeRate
from apps.influencers.services import create_sample_fulfillment
from apps.permissions.models import DataScope
from apps.tenants.models import Tenant
from tests.test_bd_settlement_rule import AUGUST, attribution, fact, instant, sample_context  # noqa: F401
from tests.test_influencer_fulfillment import make_bd_owner, user_with_permissions


pytestmark = pytest.mark.django_db


def current_sample(context, *, cost=Decimal("5"), currency="CNY"):
    QuerySet.update(
        BdSampleAttributionSnapshot.objects.filter(pk=context.sample.pk),
        sampled_at=instant(8, 1), cost_amount=cost, currency=currency,
    )
    context.sample.refresh_from_db()


def report(context, **kwargs):
    return build_bd_performance(tenant=context.tenant, **AUGUST, **kwargs)


@pytest.mark.parametrize("standard", [None, Decimal("0"), Decimal("20")])
@pytest.mark.parametrize("ads", [None, Decimal("0"), Decimal("10")])
def test_null_zero_and_actual_commissions_never_use_estimates(sample_context, standard, ads):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=standard,
                        actual_paid_shop_ads_commission=ads, estimated_paid_commission=Decimal("9999")))
    result = report(c)
    assert result["cost_basis"] == BD_COST_BASIS == "sample_plus_actual_commissions"
    for metrics in (result["rows"][0], result["totals"]):
        known_standard = (standard or Decimal("0")) * Decimal("0.125")
        known_ads = (ads or Decimal("0")) * Decimal("0.125")
        complete = standard is not None and ads is not None
        assert metrics["cost_basis"] == BD_COST_BASIS and metrics["currency"] == "CNY"
        assert metrics["sample_cost"] == metrics["known_sample_cost"] == "5.0000"
        assert metrics["sample_cost_complete"] is True
        assert metrics["known_actual_standard_commission"] == f"{known_standard:.4f}"
        assert metrics["actual_standard_commission"] == (f"{known_standard:.4f}" if standard is not None else None)
        assert metrics["actual_standard_commission_complete"] is (standard is not None)
        assert metrics["known_actual_ads_commission"] == f"{known_ads:.4f}"
        assert metrics["actual_ads_commission"] == (f"{known_ads:.4f}" if ads is not None else None)
        assert metrics["actual_ads_commission_complete"] is (ads is not None)
        known_total = Decimal("5") + known_standard + known_ads
        assert metrics["known_total_cost"] == f"{known_total:.4f}"
        assert metrics["cost_complete"] is complete
        assert metrics["total_cost"] == metrics["investment"] == (f"{known_total:.4f}" if complete else None)
        assert metrics["commission"] == metrics["actual_standard_commission"]
        assert metrics["missing_actual_standard_commission_count"] == int(standard is None)
        assert metrics["missing_actual_ads_commission_count"] == int(ads is None)
        assert metrics["missing_commission_count"] == int(standard is None)
        assert metrics["missing_sample_cost_count"] == metrics["missing_cost_count"] == 0
        assert metrics["roi"] == (f"{Decimal('12.5') / known_total:.4f}" if complete else None)


def test_missing_sample_cost_does_not_discard_known_order_costs(sample_context):
    c = sample_context
    current_sample(c, cost=None)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10")))
    metrics = report(c)["totals"]
    assert metrics["sample_cost"] is None and metrics["known_sample_cost"] == "0.0000"
    assert metrics["missing_sample_cost_count"] == metrics["missing_cost_count"] == 1
    assert metrics["actual_standard_commission"] == "2.5000" and metrics["actual_ads_commission"] == "1.2500"
    assert metrics["known_total_cost"] == "3.7500" and metrics["total_cost"] is None
    assert metrics["amount_complete"] is True and metrics["cost_complete"] is False and metrics["roi"] is None


def test_missing_gmv_keeps_independent_commissions_and_complete_cost(sample_context):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, estimated_commission_base=None, actual_paid_commission=Decimal("20"),
                        actual_paid_shop_ads_commission=Decimal("10")))
    metrics = report(c)["totals"]
    assert metrics["gmv"] is None and metrics["missing_estimated_commission_base_count"] == 1
    assert metrics["actual_standard_commission"] == "2.5000" and metrics["actual_ads_commission"] == "1.2500"
    assert metrics["total_cost"] == "8.7500" and metrics["cost_complete"] is True
    assert metrics["roi"] is None


def test_gmv_fx_failure_cannot_short_circuit_commission_accumulation(sample_context, monkeypatch):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10")))
    original = _RateResolver.convert

    def fail_gmv_only(resolver, value, base, quote, on_date):
        if value == Decimal("100"):
            return None, [{"source": "missing", "base_currency": base, "quote_currency": quote}]
        return original(resolver, value, base, quote, on_date)

    monkeypatch.setattr(_RateResolver, "convert", fail_gmv_only)
    metrics = report(c)["totals"]
    assert metrics["gmv"] is None and metrics["missing_amount_exchange_rate_count"] == 1
    assert metrics["actual_standard_commission"] == "2.5000" and metrics["actual_ads_commission"] == "1.2500"
    assert metrics["total_cost"] == "8.7500" and metrics["roi"] is None


@pytest.mark.parametrize("base_amount", [None, Decimal("0"), Decimal("100")])
def test_order_fx_failure_counts_each_independent_cost_and_keeps_sample(sample_context, base_amount):
    c = sample_context
    current_sample(c)
    for exchange_rate in ExchangeRate.objects.filter(tenant=c.tenant):
        exchange_rate.is_active = False
        exchange_rate.save(update_fields=["is_active"])
    attribution(c, fact(c.tenant, estimated_commission_base=base_amount, actual_paid_commission=None,
                        actual_paid_shop_ads_commission=Decimal("10")))
    metrics = report(c)["totals"]
    assert metrics["sample_cost"] == "5.0000" and metrics["sample_cost_complete"] is True
    assert metrics["missing_actual_standard_commission_count"] == 1
    assert metrics["missing_actual_standard_commission_exchange_rate_count"] == 0
    assert metrics["missing_actual_ads_commission_count"] == 0
    assert metrics["missing_actual_ads_commission_exchange_rate_count"] == 1
    assert metrics["missing_amount_exchange_rate_count"] == int(base_amount == Decimal("100"))
    assert metrics["known_actual_ads_commission"] == "0.0000" and metrics["actual_ads_commission"] is None
    assert metrics["known_total_cost"] == "5.0000" and metrics["total_cost"] is None and metrics["roi"] is None


def test_sample_fx_failure_keeps_order_costs_complete(sample_context):
    c = sample_context
    current_sample(c, currency="MYR")
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10")))
    metrics = report(c)["totals"]
    assert metrics["sample_cost"] is None and metrics["missing_sample_cost_count"] == 0
    assert metrics["missing_sample_cost_exchange_rate_count"] == 1
    assert metrics["actual_standard_commission_complete"] is True and metrics["actual_ads_commission_complete"] is True
    assert metrics["known_total_cost"] == "3.7500" and metrics["roi"] is None


def test_sample_and_order_use_their_own_business_dates_without_quantity(sample_context):
    c = sample_context
    current_sample(c, cost=Decimal("40"), currency="PHP")
    ExchangeRate.objects.create(tenant=c.tenant, created_by=c.user, base_currency="PHP", quote_currency="CNY",
                                rate=Decimal("0.2"), effective_from=date(2026, 8, 10), source="synthetic")
    attribution(c, fact(c.tenant, quantity=30, actual_paid_commission=Decimal("20"),
                        actual_paid_shop_ads_commission=Decimal("5")))
    metrics = report(c)["totals"]
    assert metrics["sample_cost"] == "5.0000" and metrics["actual_standard_commission"] == "4.0000"
    assert metrics["actual_ads_commission"] == "1.0000" and metrics["total_cost"] == "10.0000"
    assert metrics["quantity"] == 30 and metrics["gmv"] == "20.0000" and metrics["roi"] == "2.0000"


def test_eligibility_incomplete_does_not_mark_sample_cost_incomplete(sample_context):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10")))
    fact(c.tenant, name="unknown-eligibility", settlement_status=None)
    metrics = report(c)["totals"]
    assert metrics["eligibility_complete"] is False and metrics["sample_cost_complete"] is True
    assert metrics["sample_cost"] == "5.0000"
    assert metrics["known_actual_standard_commission"] == "2.5000" and metrics["actual_standard_commission"] is None
    assert metrics["known_actual_ads_commission"] == "1.2500" and metrics["actual_ads_commission"] is None
    assert metrics["missing_actual_standard_commission_count"] == metrics["missing_actual_ads_commission_count"] == 0
    assert metrics["actual_standard_commission_complete"] is False and metrics["actual_ads_commission_complete"] is False
    assert metrics["known_total_cost"] == "8.7500" and metrics["cost_complete"] is False and metrics["roi"] is None


def test_historical_samples_keep_owner_but_not_current_month_sample_cost(sample_context):
    c = sample_context
    QuerySet.update(BdSampleAttributionSnapshot.objects.filter(pk=c.sample.pk), cost_amount=Decimal("999"))
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10")))
    result = report(c)
    assert result["rows"][0]["owner_id"] == c.user.pk
    assert result["totals"]["samples"] == 0 and result["totals"]["sample_cost"] == "0.0000"
    assert result["totals"]["total_cost"] == "3.7500" and result["totals"]["roi"] == "3.3333"


def test_commissions_use_current_strict_sku_dedup_not_order_or_source_grain(sample_context):
    c = sample_context
    current_sample(c)
    first = fact(c.tenant, source="aaa", actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10"))
    attribution(c, first)
    attribution(c, first, version="bd-attribution-v1-strict")
    attribution(c, fact(c.tenant, source="zzz", when=instant() + timedelta(minutes=1),
                        actual_paid_commission=Decimal("9999"), actual_paid_shop_ads_commission=Decimal("8888")))
    attribution(c, fact(c.tenant, sku_id="sku-2", estimated_commission_base=Decimal("40"), quantity=30,
                        actual_paid_commission=Decimal("8"), actual_paid_shop_ads_commission=Decimal("4")))
    metrics = report(c)["totals"]
    assert metrics["valid_orders"] == 1 and metrics["quantity"] == 33
    assert metrics["gmv"] == "17.5000" and metrics["actual_standard_commission"] == "3.5000"
    assert metrics["actual_ads_commission"] == "1.7500" and metrics["total_cost"] == "10.2500"


def test_cost_and_eligibility_aggregates_are_tenant_scoped_and_read_only(sample_context):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=Decimal("10")))
    foreign = Tenant.objects.create(name="Synthetic foreign cost", code="synthetic-foreign-cost")
    fact(foreign, settlement_status=None, actual_paid_commission=Decimal("9000"),
         actual_paid_shop_ads_commission=Decimal("8000"))
    with CaptureQueriesContext(connection) as queries:
        result = report(c)
    assert all(query["sql"].split()[0] == "SELECT" for query in queries)
    assert result["eligibility_diagnostic"]["order_row_count"] == 1
    assert result["totals"]["eligibility_complete"] is True and result["totals"]["total_cost"] == "8.7500"
    assert [row["owner_id"] for row in result["rows"]] == [c.user.pk]


def test_ads_field_keeps_report_queries_constant_and_within_nine_selects(sample_context):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("0"), actual_paid_shop_ads_commission=Decimal("0")))
    with CaptureQueriesContext(connection) as before:
        report(c)
    for number in range(24):
        attribution(c, fact(c.tenant, name=f"synthetic-budget-{number}", actual_paid_commission=Decimal("0"),
                            actual_paid_shop_ads_commission=Decimal("0")))
    with CaptureQueriesContext(connection) as after:
        result = report(c)
    assert result["totals"]["valid_orders"] == 25
    assert len(after) == len(before) and len(after) <= 9
    assert all(query["sql"].split()[0] == "SELECT" for query in after)
    ads_reads = [query for query in after if "actual_paid_shop_ads_commission" in query["sql"]]
    assert len(ads_reads) == 1


def test_totals_sum_known_partial_components_across_owners(sample_context):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("20"), actual_paid_shop_ads_commission=None))
    other_owner = CustomUser.objects.create_user(username="synthetic-other-cost-owner", tenant=c.tenant)
    make_bd_owner(c.tenant, other_owner)
    fulfillment, _ = create_sample_fulfillment(
        user=c.user, request_key="synthetic-other-cost-sample", item_payloads=[],
        validated_data=dict(fulfillment_no="SYNTHETIC-OTHER-COST", link_type="YYJL", influencer=c.sample.influencer,
                            store=c.sample.store, owner=other_owner, external_product_id="P-2"),
    )
    other_sample = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    other = SimpleNamespace(tenant=c.tenant, sample=other_sample)
    current_sample(other, cost=None)
    attribution(other, fact(c.tenant, name="synthetic-other-cost-order", product_id="P-2",
                            actual_paid_commission=None, actual_paid_shop_ads_commission=Decimal("40")))
    result = report(c)
    owners = {row["owner_id"]: row for row in result["rows"]}
    assert owners[c.user.pk]["known_total_cost"] == "7.5000"
    assert owners[other_owner.pk]["known_total_cost"] == "5.0000"
    metrics = result["totals"]
    assert metrics["known_sample_cost"] == "5.0000" and metrics["known_actual_standard_commission"] == "2.5000"
    assert metrics["known_actual_ads_commission"] == "5.0000" and metrics["known_total_cost"] == "12.5000"
    assert metrics["missing_sample_cost_count"] == 1 and metrics["missing_actual_standard_commission_count"] == 1
    assert metrics["missing_actual_ads_commission_count"] == 1 and metrics["total_cost"] is None
    assert metrics["investment"] is None and metrics["roi"] is None


@pytest.mark.parametrize("sample_cost", [Decimal("0"), Decimal("-5")])
def test_nonpositive_complete_total_never_has_roi(sample_context, sample_cost):
    c = sample_context
    current_sample(c, cost=sample_cost)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("0"), actual_paid_shop_ads_commission=Decimal("0")))
    metrics = report(c)["totals"]
    assert metrics["cost_complete"] is True and metrics["amount_complete"] is True
    assert metrics["total_cost"] == f"{sample_cost:.4f}" and metrics["roi"] is None


def test_backend_csv_has_full_known_completeness_counts_currency_and_permissions(sample_context):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("0"), actual_paid_shop_ads_commission=None))
    _, client = user_with_permissions(c.tenant, "synthetic-cost-export", "influencers.outreach.view",
                                      "influencers.fulfillment.view")
    response = client.get("/api/internal/influencers/bd-performance/export/", {
        "start_date": "2026-08-01", "end_date": "2026-08-31",
    })
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    rows = list(csv.DictReader(StringIO(response.content.decode("utf-8"))))
    assert len(rows) == 2 and rows[-1]["owner_id"] == "TOTAL"
    for row in rows:
        assert row["currency"] == "CNY" and row["cost_basis"] == BD_COST_BASIS
        assert row["sample_cost"] == row["known_sample_cost"] == "5.0000"
        assert row["sample_cost_complete"] == "True" and row["actual_standard_commission"] == "0.0000"
        assert row["actual_standard_commission_complete"] == "True"
        assert row["actual_ads_commission"] == "" and row["known_actual_ads_commission"] == "0.0000"
        assert row["actual_ads_commission_complete"] == "False" and row["missing_actual_ads_commission_count"] == "1"
        assert row["total_cost"] == row["investment"] == row["roi"] == ""
        assert row["known_total_cost"] == "5.0000" and row["cost_complete"] == "False"
        for component in ("sample_cost", "actual_standard_commission", "actual_ads_commission"):
            assert row[f"missing_{component}_exchange_rate_count"] == "0"
    _, denied = user_with_permissions(c.tenant, "synthetic-cost-export-denied", "influencers.outreach.view")
    assert denied.get("/api/internal/influencers/bd-performance/export/").status_code == 403


@pytest.mark.parametrize("ads", [None, Decimal("0")])
def test_report_endpoint_exposes_nullable_cost_aliases_after_additive_migration(sample_context, ads):
    c = sample_context
    current_sample(c)
    attribution(c, fact(c.tenant, actual_paid_commission=Decimal("0"), actual_paid_shop_ads_commission=ads))
    _, client = user_with_permissions(c.tenant, "synthetic-cost-api", "influencers.outreach.view",
                                      "influencers.fulfillment.view")
    response = client.get("/api/internal/influencers/bd-performance/", {
        "start_date": "2026-08-01", "end_date": "2026-08-31", "currency": "CNY",
    })
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["cost_basis"] == BD_COST_BASIS
    for metrics in (payload["rows"][0], payload["totals"]):
        assert metrics["actual_ads_commission"] == ("0.0000" if ads is not None else None)
        assert metrics["actual_ads_commission_complete"] is (ads is not None)
        assert metrics["investment"] == ("5.0000" if ads is not None else None)
        assert metrics["roi"] == ("2.5000" if ads is not None else None)


@pytest.mark.parametrize("path", ["bd-performance/", "bd-performance/export/", "bd-performance/diagnostics/"])
@pytest.mark.parametrize("codes,scope", [
    ((), DataScope.ScopeType.ALL), (("influencers.outreach.view",), DataScope.ScopeType.ALL),
    (("influencers.fulfillment.view",), DataScope.ScopeType.ALL),
    (("influencers.outreach.view", "influencers.fulfillment.view"), DataScope.ScopeType.OWN),
])
def test_cost_endpoints_retain_both_permissions_and_all_data_scope(sample_context, path, codes, scope):
    _, client = user_with_permissions(sample_context.tenant, "synthetic-cost-scope-denied", *codes, scope=scope)
    assert client.get(f"/api/internal/influencers/{path}").status_code == 403
