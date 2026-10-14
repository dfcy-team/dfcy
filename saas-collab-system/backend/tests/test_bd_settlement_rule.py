"""Synthetic facts only. Run with config.settings.settlement_test / SQLite."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import hashlib
from io import StringIO
import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as ModelValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.influencers.attribution import (
    _order_values, _valid_order, affiliate_order_row_hash, affiliate_order_source_row_key,
    build_bd_performance, refresh_order_attributions, rule_version_for,
)
from apps.influencers.management.commands.import_affiliate_orders_csv import Command, _column_map, _parse_row
from apps.influencers.models import (
    AffiliateImportState, AffiliateOrderRevision, AffiliateOrderSnapshot,
    BdOrderAttributionSnapshot, BdSampleAttributionSnapshot, ExchangeRate, Influencer,
)
from apps.influencers.services import create_sample_fulfillment
from apps.influencers.settlement import INELIGIBLE, SETTLED, TO_SETTLE
from apps.influencers.tasks import HISTORICAL_ATTRIBUTION_SOURCE, refresh_affiliate_order_attributions_task
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import make_bd_owner, store_for


pytestmark = pytest.mark.django_db
AUGUST = {"start_date": date(2026, 8, 1), "end_date": date(2026, 8, 31)}


def instant(month=8, day=16):
    return datetime(2026, month, day, 12, tzinfo=dt_timezone.utc)


def fact(tenant, *, name="synthetic-order", when=None, **overrides):
    values = dict(tenant=tenant, source="synthetic", data_time=when or instant(), shop_abbr="store-affiliate",
                  site="PH", order_id=name, sku_id="sku-1", product_id="P-1", currency="PHP", quantity=3,
                  payment_amount=Decimal("9999"), estimated_commission_base=Decimal("100"),
                  creator_username="creator-account", creator_username_normalized="creator-account",
                  fully_returned="no", settlement_status=SETTLED, order_status="delivered",
                  actual_paid_commission=None, estimated_paid_commission=None, source_updated_at=instant())
    values.update(overrides)
    values["source_row_key"] = affiliate_order_source_row_key(**{
        key: values[key] for key in ("data_time", "shop_abbr", "site", "order_id", "sku_id")
    })
    order = AffiliateOrderSnapshot(**values)
    order.row_hash = affiliate_order_row_hash(_order_values(order))
    order.save()
    return order


@pytest.fixture
def sample_context():
    tenant = Tenant.objects.create(name="Synthetic settlement", code="synthetic-settlement")
    user = CustomUser.objects.create_user(username="synthetic-settlement-owner", tenant=tenant)
    make_bd_owner(tenant, user)
    ExchangeRate.objects.create(
        tenant=tenant, created_by=user, base_currency="PHP", quote_currency="CNY",
        rate=Decimal("0.125"), effective_from=date(2026, 7, 1), source="synthetic",
    )
    store = store_for(tenant, "store-affiliate")
    influencer = Influencer.objects.create(tenant=tenant, code="synthetic-creator", name="Synthetic creator",
                                          platform="tiktok", handle="creator-account")
    fulfillment, _ = create_sample_fulfillment(
        user=user, request_key="synthetic-settlement-sample", item_payloads=[],
        validated_data=dict(fulfillment_no="SYNTHETIC-SAMPLE", link_type="YYJL", influencer=influencer,
                            store=store, owner=user, external_product_id="P-1", product_name_snapshot="Synthetic"),
    )
    sample = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    QuerySet.update(BdSampleAttributionSnapshot.objects.filter(pk=sample.pk), sampled_at=instant(7, 1),
                    product_id="P-1", shop_abbr="store-affiliate", site="PH")
    sample.refresh_from_db()
    return SimpleNamespace(tenant=tenant, user=user, sample=sample)


def attribution(context, order, *, version=None):
    return BdOrderAttributionSnapshot.objects.create(
        tenant=context.tenant, order_snapshot=order, sample_attribution=context.sample,
        owner=context.sample.owner, influencer=context.sample.influencer, store=context.sample.store,
        order_id=order.order_id, sku_id=order.sku_id, product_id=order.product_id, rule="strict",
        rule_version=version or rule_version_for("strict"),
    )


def csv_values(**overrides):
    row = dict(data_time="2026-08-16T12:00:00+00:00", shop_abbr="store-affiliate", site="PH",
               order_id="synthetic-csv", sku_id="sku-1", product_id="P-1", creator_username="creator-account",
               payment_amount="9999", estimated_commission_base="100", currency="PHP", quantity="3",
               fully_returned="no", order_status="delivered", export_time="2026-08-16T12:00:00+00:00")
    row.update(overrides)
    return _parse_row(row, _column_map(list(row)), "synthetic")


def upsert(tenant, values):
    command = Command()
    command._store_map = {}
    with transaction.atomic():
        return command._upsert(tenant, values)


@pytest.mark.parametrize("status,refund,eligible", [
    (SETTLED, "no", True), (SETTLED, " \u5426 ", True), (SETTLED, "FALSE", True),
    (SETTLED, "0", True), (SETTLED, "N", True), (SETTLED, "maybe", False),
    (SETTLED, "", False), (SETTLED, None, False), (SETTLED, "yes", False),
    (None, "no", False), ("", "no", False), (TO_SETTLE, "no", False), (INELIGIBLE, "no", False),
])
def test_eligibility_has_no_fulfillment_fallback(status, refund, eligible):
    assert _valid_order(SimpleNamespace(settlement_status=status, fully_returned=refund, order_status="COMPLETED")) is eligible


def test_null_hash_compatible_and_known_hash_auditable(sample_context):
    order = fact(sample_context.tenant, settlement_status=None)
    values = _order_values(order)
    legacy = {key: value for key, value in values.items()
              if key not in {"settlement_status", "actual_paid_shop_ads_commission"}}
    expected = hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert affiliate_order_row_hash(values) == affiliate_order_row_hash(legacy) == expected == order.row_hash
    before_key = order.source_row_key
    order.settlement_status = SETTLED
    assert affiliate_order_row_hash(_order_values(order)) != expected
    assert order.source_row_key == before_key
    assert "settlement_status" in values and values["settlement_status"] is None
    assert affiliate_order_row_hash({**legacy, "settlement_status": ""}) != expected


def test_new_missing_refund_and_independent_csv_field(sample_context):
    assert AffiliateOrderSnapshot().fully_returned == ""
    parsed = csv_values(settlement_status="SETTLED", fully_returned="")
    assert parsed["settlement_status"] == SETTLED and parsed["fully_returned"] == ""
    created, order = upsert(sample_context.tenant, parsed)
    assert created == "created" and not _valid_order(order)
    assert csv_values(order_status="SETTLED")["settlement_status"] is None
    assert csv_values(**{"\u7ed3\u7b97\u72b6\u6001": "\u5f85\u786e\u8ba4"})["settlement_status"] == TO_SETTLE
    field = AffiliateOrderSnapshot._meta.get_field("settlement_status")
    assert field.clean(None, order) is None
    with pytest.raises(ModelValidationError):
        field.clean("UNRECOGNIZED", order)


def test_same_timestamp_only_settlement_completion_and_replay(sample_context):
    tenant = sample_context.tenant
    assert upsert(tenant, csv_values())[0] == "created"
    old = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    old_hash, old_key = old.row_hash, old.source_row_key
    assert upsert(tenant, csv_values(settlement_status="SETTLED", payment_amount="10000"))[0] == "conflict"
    assert upsert(tenant, csv_values(settlement_status="SETTLED"))[0] == "updated"
    assert upsert(tenant, csv_values(settlement_status="SETTLED"))[0] == "noop"
    assert upsert(tenant, csv_values(settlement_status="INELIGIBLE"))[0] == "conflict"
    revision = AffiliateOrderRevision.objects.get(tenant=tenant)
    old.refresh_from_db()
    assert old.source_row_key == old_key and old.order_status == "delivered"
    assert revision.before_hash == old_hash and revision.after_hash == old.row_hash
    assert revision.before_values["settlement_status"] is None and revision.after_values["settlement_status"] == SETTLED
    assert affiliate_order_row_hash(revision.before_values) == revision.before_hash
    assert affiliate_order_row_hash(revision.after_values) == revision.after_hash


@pytest.mark.parametrize("incoming", [{}, {"settlement_status": None}, {"settlement_status": ""}, {"settlement_status": "  "}])
def test_missing_does_not_erase_known_status(sample_context, incoming):
    tenant = sample_context.tenant
    upsert(tenant, csv_values(settlement_status="SETTLED"))
    assert upsert(tenant, csv_values(**incoming))[0] == "noop"
    assert upsert(tenant, csv_values(**incoming, export_time="2026-08-17T12:00:00+00:00"))[0] == "updated"
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert order.settlement_status == SETTLED and order.order_status == "delivered"
    assert AffiliateOrderRevision.objects.get(tenant=tenant).after_values["settlement_status"] == SETTLED


def test_stale_and_unknown_are_rejected_without_writes(sample_context):
    tenant = sample_context.tenant
    upsert(tenant, csv_values())
    assert upsert(tenant, csv_values(settlement_status="SETTLED", export_time="2026-08-15T12:00:00+00:00"))[0] == "rejected"
    with pytest.raises(ValueError, match="settlement_status: unknown_enum"):
        csv_values(settlement_status="UNKNOWN")
    assert AffiliateOrderSnapshot.objects.get(tenant=tenant).settlement_status is None
    assert not AffiliateOrderRevision.objects.filter(tenant=tenant).exists()


def test_revision_failure_rolls_back_completion(sample_context, monkeypatch):
    tenant = sample_context.tenant
    upsert(tenant, csv_values())
    old_hash = AffiliateOrderSnapshot.objects.get(tenant=tenant).row_hash
    def fail(**kwargs):
        raise RuntimeError("synthetic-audit-failure")
    monkeypatch.setattr(AffiliateOrderRevision.objects, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic-audit-failure"):
        upsert(tenant, csv_values(settlement_status="SETTLED"))
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert order.settlement_status is None and order.row_hash == old_hash


@pytest.mark.parametrize("failure", ["lost_token", "expired", "wrong_status"])
def test_batch_lease_failure_aborts_without_fact_audit_or_counter_writes(sample_context, failure):
    tenant = sample_context.tenant
    command = Command()
    command._store_map, command._changed_order_ids = {}, set()
    token = command._acquire_lease(tenant, "synthetic", 900)
    state = AffiliateImportState.objects.get(tenant=tenant, source="synthetic")
    changes = {"lease_token": "replacement-synthetic-token"} if failure == "lost_token" else (
        {"lease_expires_at": timezone.now() - timedelta(seconds=1)} if failure == "expired" else {"status": "idle"})
    QuerySet.update(AffiliateImportState.objects.filter(pk=state.pk), **changes)
    state.refresh_from_db()
    previous = (state.lease_token, state.lease_expires_at, state.status)
    counts = {key: 0 for key in ("created", "updated", "noop", "conflict", "rejected")}
    with pytest.raises(CommandError, match="lease lost or expired"):
        command._process_batch(tenant, [csv_values(settlement_status="SETTLED")], counts)
    state.refresh_from_db()
    assert (state.lease_token, state.lease_expires_at, state.status) == previous
    assert not AffiliateOrderSnapshot.objects.filter(tenant=tenant).exists()
    assert not AffiliateOrderRevision.objects.filter(tenant=tenant).exists()
    assert not any(counts.values()) and not command._changed_order_ids
    if failure == "lost_token":
        command._release_lease(tenant, "synthetic", token, status="failed", counts=counts)
        state.refresh_from_db()
        assert (state.lease_token, state.lease_expires_at, state.status) == previous


def test_valid_batch_renews_lease_and_records_only_committed_ids(sample_context):
    tenant = sample_context.tenant
    command = Command()
    command._store_map, command._changed_order_ids = {}, set()
    token = command._acquire_lease(tenant, "synthetic", 900)
    state = AffiliateImportState.objects.get(tenant=tenant, source="synthetic")
    QuerySet.update(AffiliateImportState.objects.filter(pk=state.pk), lease_expires_at=timezone.now() + timedelta(seconds=10))
    counts = {key: 0 for key in ("created", "updated", "noop", "conflict", "rejected")}
    command._process_batch(tenant, [csv_values(settlement_status="SETTLED")], counts)
    state.refresh_from_db()
    assert state.lease_token == token and state.lease_expires_at > timezone.now() + timedelta(seconds=800)
    order = AffiliateOrderSnapshot.objects.get(tenant=tenant)
    assert counts["created"] == 1 and command._changed_order_ids == {order.pk}


def test_failed_batch_rolls_back_lease_renewal_facts_and_counters(sample_context, monkeypatch):
    tenant = sample_context.tenant
    command = Command()
    command._store_map, command._changed_order_ids = {}, set()
    command._acquire_lease(tenant, "synthetic", 900)
    state = AffiliateImportState.objects.get(tenant=tenant, source="synthetic")
    expiry = state.lease_expires_at
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-batch-stop")
    monkeypatch.setattr(command, "_upsert", fail)
    counts = {key: 0 for key in ("created", "updated", "noop", "conflict", "rejected")}
    with pytest.raises(RuntimeError, match="synthetic-batch-stop"):
        command._process_batch(tenant, [csv_values(settlement_status="SETTLED")], counts)
    state.refresh_from_db()
    assert state.lease_expires_at == expiry and not any(counts.values())
    assert not command._changed_order_ids and not AffiliateOrderSnapshot.objects.filter(tenant=tenant).exists()


def test_august_cleanup_preserves_v1_other_months_and_common_owner(sample_context):
    c = sample_context
    july = fact(c.tenant, name="july", when=instant(7, 31))
    august = fact(c.tenant, name="august", when=instant(8, 31))
    september = fact(c.tenant, name="september", when=instant(9, 1))
    old = attribution(c, august, version="bd-attribution-v1-strict")
    july_attr, september_attr = attribution(c, july), attribution(c, september)
    result = refresh_order_attributions(tenant=c.tenant, **AUGUST)
    assert result["created"] == 1 and result["deleted"] == 0
    assert result["rule_version"] == "bd-attribution-v2-settlement-strict"
    current = BdOrderAttributionSnapshot.objects.get(order_snapshot=august, rule_version=rule_version_for("strict"))
    assert current.sample_attribution_id == old.sample_attribution_id and current.owner_id == old.owner_id
    assert refresh_order_attributions(tenant=c.tenant, **AUGUST)["noop"] == 1
    QuerySet.update(AffiliateOrderSnapshot.objects.filter(pk__in=[july.pk, august.pk, september.pk]), settlement_status=INELIGIBLE)
    assert refresh_order_attributions(tenant=c.tenant, **AUGUST)["deleted"] == 1
    assert BdOrderAttributionSnapshot.objects.filter(pk__in=[old.pk, july_attr.pk, september_attr.pk]).count() == 3
    assert not BdOrderAttributionSnapshot.objects.filter(pk=current.pk).exists()


def test_incremental_cleanup_union_is_bounded_to_changed_subset(sample_context):
    c = sample_context
    orders = [fact(c.tenant, name=str(i)) for i in range(3)]
    attrs = [attribution(c, order) for order in orders]
    cutoff = timezone.now()
    QuerySet.update(AffiliateOrderSnapshot.objects.filter(tenant=c.tenant), fully_returned="yes", updated_at=cutoff - timedelta(days=1))
    QuerySet.update(AffiliateOrderSnapshot.objects.filter(pk=orders[0].pk), updated_at=cutoff)
    result = refresh_order_attributions(tenant=c.tenant, changed_since=cutoff, order_ids=[orders[1].pk], **AUGUST)
    assert result["deleted"] == 2
    assert BdOrderAttributionSnapshot.objects.filter(pk=attrs[2].pk).exists()
    assert refresh_order_attributions(tenant=c.tenant, order_ids=[])["deleted"] == 0


def test_incremental_duplicate_cannot_mutate_outside_scope(sample_context):
    c = sample_context
    first = fact(c.tenant)
    original = attribution(c, first)
    duplicate = fact(c.tenant, when=instant() + timedelta(minutes=1), source="second-synthetic")
    result = refresh_order_attributions(tenant=c.tenant, order_ids=[duplicate.pk])
    assert result["created"] == 0 and result["deferred_out_of_scope_duplicates"] == 1
    assert BdOrderAttributionSnapshot.objects.get(tenant=c.tenant).pk == original.pk


def test_outside_duplicate_identity_uses_casefold_and_one_bounded_sql_read(sample_context):
    c = sample_context
    first = fact(c.tenant, name="stra\u00dfe")
    original = attribution(c, first)
    duplicate = fact(c.tenant, name="STRASSE", source="second-synthetic")
    with CaptureQueriesContext(connection) as queries:
        result = refresh_order_attributions(tenant=c.tenant, order_ids=[duplicate.pk])
    assert result["deferred_out_of_scope_duplicates"] == 1
    sql = [item["sql"] for item in queries if "influencers_bdorderattributionsnapshot" in item["sql"] and "NOT" in item["sql"]]
    assert len(sql) == 1 and all(word not in sql[0].upper() for word in ("LOWER(", "TRIM(", "EXISTS("))
    assert BdOrderAttributionSnapshot.objects.get(tenant=c.tenant).pk == original.pk


def test_large_unrelated_outside_history_does_not_block_incremental_orders(sample_context, monkeypatch):
    c = sample_context
    outside = fact(c.tenant, name="outside")
    old = attribution(c, outside)
    inside = fact(c.tenant, name="inside")
    original_iterator = QuerySet.iterator
    def large_history(queryset, *args, **kwargs):
        if queryset.model is BdOrderAttributionSnapshot and queryset._fields:
            for number in range(50001):
                yield ("unrelated-shop", "PH", str(number), "unrelated-sku")
            return
        yield from original_iterator(queryset, *args, **kwargs)
    monkeypatch.setattr(QuerySet, "iterator", large_history)
    result = refresh_order_attributions(tenant=c.tenant, order_ids=[inside.pk])
    assert result["created"] == 1 and result["deleted"] == 0
    assert BdOrderAttributionSnapshot.objects.filter(pk=old.pk).exists()


@pytest.mark.parametrize("kwargs", [{}, {"start_date": date(2026, 8, 1)},
    {"start_date": date(2026, 8, 31), "end_date": date(2026, 8, 1)},
    {"start_date": date(2026, 8, 1), "end_date": date(2026, 9, 1)},
    {"order_ids": [True]}, {"order_ids": [-1]}, {"order_ids": [1] * 5001},
    {"rule_version": "bd-attribution-v1-strict", **AUGUST},
    {"rule_version": "bd-attribution-v2-settlement-fallback", **AUGUST},
    {"order_ids": [], "deletion_limit": 10001}, {"order_ids": [], "deletion_limit": -1}])
def test_refresh_fails_closed_on_unbounded_or_wrong_version(sample_context, kwargs):
    with pytest.raises(ValidationError):
        refresh_order_attributions(tenant=sample_context.tenant, **kwargs)


def test_refresh_pauses_for_active_importer_and_leaves_snapshots_unchanged(sample_context):
    c = sample_context
    order = fact(c.tenant)
    original = attribution(c, order)
    command = Command()
    command._acquire_lease(c.tenant, "other-synthetic-source", 900)
    with pytest.raises(ValidationError, match="import is active"):
        refresh_order_attributions(tenant=c.tenant, **AUGUST)
    assert BdOrderAttributionSnapshot.objects.get(tenant=c.tenant).pk == original.pk


def test_deletion_budget_fails_before_delete_and_preserves_v1(sample_context):
    c = sample_context
    order = fact(c.tenant, settlement_status=INELIGIBLE)
    current = attribution(c, order)
    legacy = attribution(c, order, version="bd-attribution-v1-strict")
    with pytest.raises(ValidationError, match="deletion limit exceeded"):
        refresh_order_attributions(tenant=c.tenant, deletion_limit=0, **AUGUST)
    assert BdOrderAttributionSnapshot.objects.filter(pk__in=[current.pk, legacy.pk]).count() == 2


def test_task_accepts_scoped_contract_without_advancing_history(sample_context):
    c = sample_context
    fact(c.tenant)
    state = AffiliateImportState.objects.create(tenant=c.tenant, source=HISTORICAL_ATTRIBUTION_SOURCE, cursor="17")
    result = refresh_affiliate_order_attributions_task(c.tenant.pk, start_date="2026-08-01", end_date="2026-08-31")
    state.refresh_from_db()
    assert result["status"] == "completed" and state.cursor == "17"
    assert result["modes"]["strict"]["created"] == result["modes"]["fallback"]["created"] == 1


def test_sku_grain_dedup_historical_samples_and_live_double_filter(sample_context):
    c = sample_context
    valid = fact(c.tenant, name="same-order", estimated_commission_base=Decimal("123.4567"))
    attribution(c, valid)
    duplicate = fact(c.tenant, name="same-order", when=instant() + timedelta(minutes=1))
    attribution(c, duplicate)
    for name, status, refund in (("unknown", None, "no"), ("pending", TO_SETTLE, "no"), ("unknown-refund", SETTLED, "maybe")):
        order = fact(c.tenant, name=name, settlement_status=status, fully_returned=refund)
        attribution(c, order)  # Deliberately stale snapshots must be filtered again at report time.
    report = build_bd_performance(tenant=c.tenant, currency="PHP", **AUGUST)
    assert report["totals"]["valid_orders"] == 1 and report["totals"]["quantity"] == 3
    assert report["totals"]["known_estimated_commission_base"] == "123.4567"
    assert report["totals"]["gmv"] is None and report["totals"]["roi"] is None
    assert report["totals"]["sample_count"] == 0  # July sample remains eligible for August orders.
    assert report["eligibility_diagnostic"]["verified_attributed_line_count"] == 1
    assert report["source_status"] == "incomplete"


def test_coverage_and_null_not_healthy_zero(sample_context):
    c = sample_context
    valid = fact(c.tenant)
    attribution(c, valid)
    fact(c.tenant, name="missing", settlement_status=None, fully_returned="")
    fact(c.tenant, name="unknown-refund", settlement_status=TO_SETTLE, fully_returned="maybe")
    foreign = Tenant.objects.create(name="Foreign synthetic", code="foreign-synthetic")
    foreign_order = fact(foreign, name="foreign")
    assert refresh_order_attributions(tenant=c.tenant, order_ids=[foreign_order.pk])["created"] == 0
    report = build_bd_performance(tenant=c.tenant, currency="PHP", **AUGUST)
    coverage = report["eligibility_diagnostic"]
    assert coverage["order_row_count"] == 3 and coverage["settlement_known_count"] == 2
    assert coverage["settlement_missing_count"] == 1 and coverage["refund_missing_count"] == 1
    assert coverage["refund_unknown_count"] == 1 and coverage["verified_eligible_line_count"] == 1
    assert coverage["valid_unmatched_line_count"] == 0
    assert report["totals"]["gmv"] is None and report["totals"]["gmv_php"] is None
    assert report["totals"]["known_estimated_commission_base"] == "100.0000"
    assert not report["zero_gmv_diagnostic"]["is_zero_gmv"]
    empty = build_bd_performance(tenant=c.tenant, currency="PHP", start_date=date(2026, 9, 1), end_date=date(2026, 9, 2))
    assert empty["totals"]["gmv"] is None and empty["source_status"] == "incomplete"
    assert empty["eligibility_diagnostic"]["settlement_coverage"] is None


def test_known_rule_stays_complete_but_missing_cost_roi_is_null(sample_context):
    c = sample_context
    QuerySet.update(BdSampleAttributionSnapshot.objects.filter(pk=c.sample.pk), sampled_at=instant(8, 1), cost_amount=None)
    fact(c.tenant)
    refresh_order_attributions(tenant=c.tenant, **AUGUST)
    report = build_bd_performance(tenant=c.tenant, currency="PHP", **AUGUST)
    assert report["totals"]["gmv"] == "100.0000" and report["totals"]["amount_complete"]
    assert report["totals"]["missing_cost_count"] == 1 and report["totals"]["roi"] is None


def test_estimated_base_uses_tenant_fx_not_payment_or_quantity(sample_context):
    c = sample_context
    ExchangeRate.objects.create(tenant=c.tenant, created_by=c.user, base_currency="PHP", quote_currency="CNY",
                                rate=Decimal("0.2"), effective_from=date(2026, 8, 1), source="synthetic")
    fact(c.tenant, estimated_commission_base=Decimal("123.4567"))
    refresh_order_attributions(tenant=c.tenant, **AUGUST)
    report = build_bd_performance(tenant=c.tenant, currency="CNY", **AUGUST)
    assert report["totals"]["gmv"] == "24.6913"
    assert report["totals"]["gmv_php"] == "123.4567"
    assert report["totals"]["roi"] is None


def test_explicit_tenant_date_cli_contract(sample_context):
    fact(sample_context.tenant)
    output = StringIO()
    call_command("refresh_bd_order_attributions", tenant_id=sample_context.tenant.pk, start_date="2026-08-01",
                 end_date="2026-08-31", stdout=output)
    assert "created=1" in output.getvalue()
