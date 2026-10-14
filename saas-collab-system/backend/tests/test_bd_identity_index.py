import json
from io import StringIO

import pytest
from django.core.exceptions import ValidationError as ModelValidationError
from django.core.management import call_command
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError

from apps.influencers.attribution import _order_values, refresh_order_attributions
from apps.influencers.models import AffiliateOrderSnapshot, BdOrderAttributionSnapshot
from apps.influencers.order_identity import order_identity_digest
from tests.test_bd_settlement_rule import attribution, fact, sample_context  # noqa: F401

pytestmark = pytest.mark.django_db


def backfill(tenant, *args):
    output = StringIO()
    call_command("backfill_affiliate_business_identity", "--tenant-id", str(tenant.pk), *args, stdout=output)
    return json.loads(output.getvalue())


def test_canonical_identity_is_unicode_and_separator_safe():
    assert order_identity_digest([" A ", "PH", "straße", " SKU "]) == order_identity_digest(["a", "ph", "STRASSE", "sku"])
    assert order_identity_digest(["a|b", "c", "d", "e"]) != order_identity_digest(["a", "b|c", "d", "e"])


def test_incremental_collision_query_filters_identity_before_iteration(sample_context):
    c = sample_context
    first = fact(c.tenant, name="straße")
    attribution(c, first)
    duplicate = fact(c.tenant, name=" STRASSE ", source="duplicate")
    with CaptureQueriesContext(connection) as queries:
        result = refresh_order_attributions(tenant=c.tenant, order_ids=[duplicate.pk])
    assert result["deferred_out_of_scope_duplicates"] == 1
    reads = [q["sql"] for q in queries if "influencers_bdorderattributionsnapshot" in q["sql"] and "NOT" in q["sql"]]
    assert reads and all("business_identity_digest" in sql and " IN " in sql for sql in reads)
    assert BdOrderAttributionSnapshot.objects.filter(tenant=c.tenant).count() == 1


def test_missing_index_fails_without_writes_and_bounded_backfill_is_fact_preserving(sample_context):
    c = sample_context
    orders = [fact(c.tenant, name=str(i)) for i in range(3)]
    before = [(_order_values(o), o.row_hash, o.updated_at) for o in orders]
    QuerySet.update(AffiliateOrderSnapshot.objects.filter(pk__in=[o.pk for o in orders]), business_identity_digest=None)
    with pytest.raises(ValidationError, match="backfill_affiliate_business_identity"):
        refresh_order_attributions(tenant=c.tenant, order_ids=[orders[0].pk])
    assert not BdOrderAttributionSnapshot.objects.filter(tenant=c.tenant).exists()
    with CaptureQueriesContext(connection) as queries:
        dry = backfill(c.tenant)
    assert dry["target_rows"] == 0
    assert not any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries)
    assert backfill(c.tenant, "--apply", "--batch-size", "2")["status"] == "partial"
    assert backfill(c.tenant, "--apply", "--batch-size", "2")["status"] == "passed"
    assert backfill(c.tenant, "--apply")["target_rows"] == 0
    for order, expected in zip(orders, before):
        order.refresh_from_db()
        assert (_order_values(order), order.row_hash, order.updated_at) == expected


def test_partial_save_uses_persisted_identity_and_blocks_bulk_identity_changes(sample_context):
    order = fact(sample_context.tenant)
    digest = order.business_identity_digest
    order.order_id = "unsaved-identity"
    order.quantity = 5
    order.save(update_fields=["quantity"])
    order.refresh_from_db()
    assert order.business_identity_digest == digest and order.order_id != "unsaved-identity"
    with pytest.raises(ModelValidationError):
        AffiliateOrderSnapshot.objects.filter(pk=order.pk).update(order_id="unsafe")
    order.quantity = 7
    order.save(update_fields=(name for name in ["quantity"]))
    order.refresh_from_db()
    assert order.quantity == 7 and order.business_identity_digest == digest
    with pytest.raises(ModelValidationError, match="Bulk create is disabled"):
        AffiliateOrderSnapshot.objects.bulk_create([order])
    with pytest.raises(ModelValidationError, match="Bulk update is disabled"):
        AffiliateOrderSnapshot.objects.bulk_update([order], ["quantity"])


def test_unrelated_history_is_not_returned_by_incremental_query(sample_context, monkeypatch):
    c = sample_context
    for i in range(30):
        attribution(c, fact(c.tenant, name=f"unrelated-{i}"))
    inside = fact(c.tenant, name="new-order")
    original = QuerySet.iterator
    observed = []
    def observe(queryset, *args, **kwargs):
        for row in original(queryset, *args, **kwargs):
            if queryset.model is BdOrderAttributionSnapshot and queryset._fields:
                observed.append(row)
            yield row
    monkeypatch.setattr(QuerySet, "iterator", observe)
    assert refresh_order_attributions(tenant=c.tenant, order_ids=[inside.pk])["created"] == 1
    assert observed == []


def test_release_readiness_is_read_only_and_unknown_is_blocked(sample_context):
    c = sample_context
    fact(c.tenant, settlement_status=None)
    output = StringIO()
    with CaptureQueriesContext(connection) as queries:
        call_command("check_bd_release_readiness", "--tenant-id", str(c.tenant.pk),
                     "--start-date", "2026-08-01", "--end-date", "2026-08-31", stdout=output)
    receipt = json.loads(output.getvalue())
    assert receipt["status"] == "blocked" and receipt["source_rows"] == 1
    assert receipt["eligibility"]["settlement_missing_count"] == 1
    assert all(q["sql"].lstrip().startswith("SELECT") for q in queries)
