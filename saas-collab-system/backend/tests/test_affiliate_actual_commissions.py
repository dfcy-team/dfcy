"""Legacy CSV/hash compatibility and audited monotonic actual-commission fills."""

from decimal import Decimal
import hashlib
import json

import pytest

from apps.influencers.attribution import _order_values, affiliate_order_row_hash
from apps.influencers.models import AffiliateOrderRevision, AffiliateOrderSnapshot
from apps.tenants.models import Tenant
from tests.test_bd_settlement_rule import csv_values, fact, sample_context, upsert  # noqa: F401


pytestmark = pytest.mark.django_db
ADS_FIELD = "actual_paid_shop_ads_commission"


@pytest.mark.parametrize("alias", [ADS_FIELD, "actual_shop_ads_commission", "actual_ads_commission",
                                   "actual shop ads commission", "\u5b9e\u9645\u5e97\u94fa\u5e7f\u544a\u4f63\u91d1",
                                   "\u5b9e\u9645\u5e7f\u544a\u4f63\u91d1"])
@pytest.mark.parametrize("value,expected", [("", None), ("0", Decimal("0")), ("1.2345", Decimal("1.2345"))])
def test_ads_csv_aliases_preserve_null_zero_and_exact_decimal(alias, value, expected):
    assert csv_values(**{alias: value})[ADS_FIELD] == expected
    legacy = csv_values()
    assert ADS_FIELD not in legacy and "actual_paid_commission" not in legacy


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1.23456", "12345678901234567.0000"])
def test_ads_csv_rejects_nonfinite_or_out_of_decimal_20_4(value):
    with pytest.raises(ValueError, match=ADS_FIELD):
        csv_values(**{ADS_FIELD: value})


def test_ads_none_keeps_legacy_hash_and_explicit_zero_changes_it(sample_context):
    order = fact(sample_context.tenant, settlement_status=None)
    values = _order_values(order)
    legacy = {key: value for key, value in values.items() if key not in {"settlement_status", ADS_FIELD}}
    legacy_hash = hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert values[ADS_FIELD] is None
    assert affiliate_order_row_hash(values) == affiliate_order_row_hash(legacy) == legacy_hash == order.row_hash
    assert affiliate_order_row_hash({**values, ADS_FIELD: "0"}) != legacy_hash
    assert affiliate_order_row_hash({**values, ADS_FIELD: "1.2345"}) != legacy_hash


def test_all_new_nullable_fields_preserve_main_legacy_hash(sample_context):
    order = fact(sample_context.tenant, settlement_status=None, estimated_commission_base=None)
    values = _order_values(order)
    new_fields = {"estimated_commission_base", "settlement_status", ADS_FIELD}
    legacy = {key: value for key, value in values.items() if key not in new_fields}
    legacy_hash = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
    ).hexdigest()
    assert affiliate_order_row_hash(values) == legacy_hash
    for field in new_fields:
        known = "已结算" if field == "settlement_status" else "0"
        assert affiliate_order_row_hash({**values, field: known}) != legacy_hash


@pytest.mark.parametrize("fields", [{"actual_paid_commission": "0"}, {ADS_FIELD: "0"},
                                    {"actual_paid_commission": "1.2345", ADS_FIELD: "2.3456"}])
def test_same_timestamp_allows_only_null_to_known_commissions_and_replay(sample_context, fields):
    tenant = sample_context.tenant
    assert upsert(tenant, csv_values(settlement_status="SETTLED"))[0] == "created"
    before = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    old_hash, old_key = before.row_hash, before.source_row_key
    incoming = csv_values(settlement_status="SETTLED", **fields)
    assert upsert(tenant, incoming)[0] == "updated"
    assert upsert(tenant, incoming)[0] == "noop"
    before.refresh_from_db()
    assert before.source_row_key == old_key
    revision = AffiliateOrderRevision.objects.get(tenant=tenant)
    assert revision.before_hash == old_hash and revision.after_hash == before.row_hash
    changes = {key for key in revision.before_values if revision.before_values[key] != revision.after_values[key]}
    assert changes == set(fields)
    for field, value in fields.items():
        assert revision.before_values[field] is None and Decimal(revision.after_values[field]) == Decimal(value)
    assert affiliate_order_row_hash(revision.before_values) == revision.before_hash
    assert affiliate_order_row_hash(revision.after_values) == revision.after_hash


def test_stepwise_commission_completion_never_rewrites_or_clears_known_same_timestamp(sample_context):
    tenant = sample_context.tenant
    upsert(tenant, csv_values(settlement_status="SETTLED"))
    assert upsert(tenant, csv_values(settlement_status="SETTLED", actual_paid_commission="0"))[0] == "updated"
    assert upsert(tenant, csv_values(settlement_status="SETTLED", **{ADS_FIELD: "2"}))[0] == "updated"
    assert upsert(tenant, csv_values(settlement_status="SETTLED", actual_paid_commission="1"))[0] == "conflict"
    assert upsert(tenant, csv_values(settlement_status="SETTLED", **{ADS_FIELD: ""}))[0] == "conflict"
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert order.actual_paid_commission == Decimal("0") and order.actual_paid_shop_ads_commission == Decimal("2")
    assert list(AffiliateOrderRevision.objects.filter(tenant=tenant).values_list("revision_no", flat=True)) == [1, 2]


@pytest.mark.parametrize("changes", [
    {"payment_amount": "8888"}, {"quantity": "4"}, {"product_id": "P-2"},
    {"estimated_commission_base": "101"}, {"settlement_status": "INELIGIBLE"},
    {"creator_username": "another-creator"},
])
def test_commission_fill_conflicts_when_any_other_fact_changes(sample_context, changes):
    tenant = sample_context.tenant
    upsert(tenant, csv_values(settlement_status="SETTLED"))
    incoming = csv_values(**{"settlement_status": "SETTLED", "actual_paid_commission": "1", ADS_FIELD: "2", **changes})
    assert upsert(tenant, incoming)[0] == "conflict"
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert order.actual_paid_commission is None and order.actual_paid_shop_ads_commission is None
    assert not AffiliateOrderRevision.objects.filter(tenant=tenant).exists()


def test_legacy_absent_columns_cannot_erase_known_commissions_even_with_newer_export(sample_context):
    tenant = sample_context.tenant
    upsert(tenant, csv_values(settlement_status="SETTLED", actual_paid_commission="1.2345", **{ADS_FIELD: "0"}))
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    old_hash = order.row_hash
    assert upsert(tenant, csv_values(settlement_status="SETTLED"))[0] == "noop"
    order.refresh_from_db()
    assert order.row_hash == old_hash
    incoming = csv_values(settlement_status="SETTLED", export_time="2026-08-17T12:00:00+00:00")
    incoming.pop("estimated_commission_base")
    assert upsert(tenant, incoming)[0] == "updated"
    order.refresh_from_db()
    assert order.actual_paid_commission == Decimal("1.2345") and order.actual_paid_shop_ads_commission == Decimal("0")
    assert order.estimated_commission_base == Decimal("100")
    revision = AffiliateOrderRevision.objects.get(tenant=tenant)
    assert revision.before_values[ADS_FIELD] == revision.after_values[ADS_FIELD] == "0"
    assert revision.before_values["actual_paid_commission"] == revision.after_values["actual_paid_commission"] == "1.2345"


def test_stale_fill_and_foreign_tenant_cannot_modify_local_commissions(sample_context):
    tenant = sample_context.tenant
    upsert(tenant, csv_values(settlement_status="SETTLED"))
    stale = csv_values(settlement_status="SETTLED", actual_paid_commission="1", **{ADS_FIELD: "2"},
                       export_time="2026-08-15T12:00:00+00:00")
    assert upsert(tenant, stale)[0] == "rejected"
    foreign = Tenant.objects.create(name="Synthetic foreign import", code="synthetic-foreign-import")
    assert upsert(foreign, csv_values(settlement_status="SETTLED", actual_paid_commission="3", **{ADS_FIELD: "4"}))[0] == "created"
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert order.actual_paid_commission is None and order.actual_paid_shop_ads_commission is None
    assert not AffiliateOrderRevision.objects.filter(tenant=tenant).exists()


def test_two_field_fill_rolls_back_if_revision_writer_fails(sample_context, monkeypatch):
    tenant = sample_context.tenant
    upsert(tenant, csv_values(settlement_status="SETTLED"))
    old_hash = AffiliateOrderSnapshot.objects.get(tenant=tenant).row_hash

    def fail(**kwargs):
        raise RuntimeError("synthetic-commission-audit-failure")

    monkeypatch.setattr(AffiliateOrderRevision.objects, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic-commission-audit-failure"):
        upsert(tenant, csv_values(settlement_status="SETTLED", actual_paid_commission="1", **{ADS_FIELD: "2"}))
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert order.actual_paid_commission is None and order.actual_paid_shop_ads_commission is None
    assert order.row_hash == old_hash and not AffiliateOrderRevision.objects.filter(tenant=tenant).exists()
