"""Real MySQL operation probes, not a full production upgrade certification."""
import os
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.db import connection, models
from tests.test_bd_settlement_rule import sample_context  # noqa: F401

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(
    os.environ.get("PR304_DISPOSABLE") != "yes", reason="disposable MySQL only",
)]


@pytest.mark.parametrize("state", ["absent", "compatible", "incompatible"])
def test_0033_actual_mysql_column_adoption(state):
    assert connection.vendor == "mysql"
    class Probe(models.Model):
        marker = models.IntegerField()
        class Meta:
            app_label = "influencers"
            db_table = "synthetic_pr304_column_probe"
            managed = False
    with connection.schema_editor() as editor:
        editor.create_model(Probe)
    try:
        with connection.cursor() as cursor:
            if state != "absent":
                ddl = "decimal(20,4) NULL" if state == "compatible" else "decimal(18,2) NOT NULL DEFAULT 0"
                cursor.execute(f"ALTER TABLE synthetic_pr304_column_probe ADD estimated_commission_base {ddl}")
            for i in range(3):
                cursor.execute("INSERT INTO synthetic_pr304_column_probe (marker) VALUES (%s)", [i])
            if state == "compatible":
                cursor.execute("UPDATE synthetic_pr304_column_probe SET estimated_commission_base=0 WHERE marker=1")
                cursor.execute("UPDATE synthetic_pr304_column_probe SET estimated_commission_base=1.2345 WHERE marker=2")
            cursor.execute("SELECT * FROM synthetic_pr304_column_probe ORDER BY marker")
            before = cursor.fetchall()
        ensure = import_module("apps.influencers.migrations.0033_affiliate_estimated_commission_base").ensure_estimated_base_column
        registry = SimpleNamespace(get_model=lambda *args: Probe)
        with connection.schema_editor() as editor:
            if state == "incompatible":
                with pytest.raises(RuntimeError, match="incompatible"):
                    ensure(registry, editor)
            else:
                ensure(registry, editor)
                ensure(registry, editor)
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM synthetic_pr304_column_probe ORDER BY marker")
            after = cursor.fetchall()
        assert len(after) == len(before) == 3
        if state == "absent":
            assert after == tuple((*row, None) for row in before)
        else:
            assert after == before
        if state == "compatible":
            assert [row[-1] for row in after] == [None, Decimal("0"), Decimal("1.2345")]
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Probe)


def test_0038_mysql_index_and_lookup():
    assert connection.vendor == "mysql"
    from apps.influencers.models import AffiliateOrderSnapshot
    table = AffiliateOrderSnapshot._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute("SELECT COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s ORDER BY SEQ_IN_INDEX", [table, "idx_aff_order_identity"])
        assert [row[0] for row in cursor.fetchall()] == ["tenant_id", "business_identity_digest"]
        cursor.execute(f"EXPLAIN SELECT id FROM {table} WHERE tenant_id=%s AND business_identity_digest=%s", [1, "a" * 64])
        plan = dict(zip([item[0] for item in cursor.description], cursor.fetchone()))
        assert "idx_aff_order_identity" in str(plan.get("possible_keys"))


def test_single_incremental_order_with_50001_unrelated_attributions(sample_context, monkeypatch):
    from django.db.models.query import QuerySet
    from apps.influencers.attribution import refresh_order_attributions, rule_version_for
    from apps.influencers.models import AffiliateOrderSnapshot, BdOrderAttributionSnapshot
    from apps.influencers.order_identity import order_identity_digest
    from tests.test_bd_settlement_rule import fact
    c = sample_context
    template = fact(c.tenant, name="history-template")
    values = {f.attname: getattr(template, f.attname) for f in template._meta.concrete_fields if not f.primary_key}
    # Synthetic setup deliberately bypasses public bulk-write guards. Never use
    # this path for imports: source revisions and validation are not exercised.
    for start in range(0, 50001, 1000):
        batch = []
        for i in range(start, min(start + 1000, 50001)):
            identity = f"history-{i}"
            batch.append(AffiliateOrderSnapshot(**{
                **values, "source_row_key": f"{i:064x}", "order_id": identity,
                "business_identity_digest": order_identity_digest([template.shop_abbr, template.site, identity, template.sku_id]),
            }))
        QuerySet.bulk_create(AffiliateOrderSnapshot.objects.all(), batch)
        ids = AffiliateOrderSnapshot.objects.filter(tenant=c.tenant, source_row_key__in=[o.source_row_key for o in batch]).values_list("pk", "order_id")
        rows = [BdOrderAttributionSnapshot(tenant=c.tenant, order_snapshot_id=pk, sample_attribution=c.sample,
                owner=c.sample.owner, influencer=c.sample.influencer, store=c.sample.store,
                order_id=number, sku_id=template.sku_id, product_id=template.product_id,
                rule="strict", rule_version=rule_version_for("strict")) for pk, number in ids]
        QuerySet.bulk_create(BdOrderAttributionSnapshot.objects.all(), rows)
    inside = fact(c.tenant, name="new-incremental")
    original = QuerySet.iterator
    returned = []
    def observe(queryset, *args, **kwargs):
        for row in original(queryset, *args, **kwargs):
            if queryset.model is BdOrderAttributionSnapshot and queryset._fields:
                returned.append(row)
            yield row
    monkeypatch.setattr(QuerySet, "iterator", observe)
    result = refresh_order_attributions(tenant=c.tenant, order_ids=[inside.pk])
    assert result["created"] == 1 and returned == []
    assert BdOrderAttributionSnapshot.objects.filter(tenant=c.tenant).count() == 50002
