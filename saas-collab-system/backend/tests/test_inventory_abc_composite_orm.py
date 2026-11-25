from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.commerce.models import SalesOrderBundleSnapshot, SalesOrderItem
from apps.integrations.models import HistorySyncSegment, SyncJob, SyncRun
from apps.masterdata.models import CountrySiteMaster, InventoryABCEntry, InventoryABCRun, InventoryObservationSettings
from apps.products.models import ProductBundleVersion, ProductBundleVersionComponent, ProductSKU, ProductSPU
from apps.sales_management.abc_access import decorate_rows, filter_skus, published_run
from apps.sales_management.abc_service import ABC_POLICY_VERSION, calculate_country, _previous_entries
from tests.test_country_inventory_decisions import NOW, history_coverage, sale
from tests.test_sales_management import create_scope


@pytest.fixture
def abc_scope(db, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    tenant, _, store, _ = create_scope("composite-abc")
    actor = get_user_model().objects.create_user(
        username="composite-admin", tenant=tenant, user_type="internal", is_superuser=True,
    )
    country = CountrySiteMaster.objects.create(
        tenant=tenant, code="ph", name="Philippines", country_code="PH", timezone=store.timezone,
        currency=store.currency,
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="ABC-SPU")
    first = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="ABC-1")
    second = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="ABC-2")
    return actor, country, store, spu, first, second


def _add_coverage(actor, store, upper=None):
    tenant = actor.tenant
    sales_segment = history_coverage(tenant, store, actor, lower=NOW - timedelta(days=120), upper=upper)
    sales_job = sales_segment.sync_job
    refund_job = SyncJob.objects.create(
        tenant=tenant, integration_config=sales_job.integration_config,
        store_authorization=sales_job.store_authorization, resource_type="refund_return",
    )
    refund_segment = HistorySyncSegment.objects.create(
        batch=sales_segment.batch, sync_job=refund_job, sequence=2, status="success",
        scope={**sales_segment.scope, "_refund_history_policy": "page20_day1_v1"},
    )
    SyncRun.objects.create(
        tenant=tenant, sync_job=refund_job, history_segment=refund_segment, run_id="refund-coverage",
        idempotency_key="refund-coverage", status="success",
    )


@pytest.mark.parametrize("invalid,country_mismatch", [(False, False), (True, False), (False, True)])
def test_bundle_only_component_has_population_and_maturity(abc_scope, invalid, country_mismatch):
    actor, country, store, spu, first, second = abc_scope
    _add_coverage(actor, store)
    bundle_spu = ProductSPU.objects.create(tenant=actor.tenant, spu_code="ONLY-PACK", product_type="bundle")
    bundle = ProductSKU.objects.create(tenant=actor.tenant, spu=bundle_spu, sku_code="ONLY-PACK-1")
    order = sale(actor.tenant, store, bundle, "only-bundle", 31, 2)
    order.paid_at_utc = order.created_at_utc + timedelta(days=1)
    order.save(update_fields=["paid_at_utc"])
    version = ProductBundleVersion.objects.create(
        tenant=actor.tenant, bundle_sku=bundle, version=1, created_by=actor,
        effective_at=order.created_at_utc - timedelta(days=1),
    )
    SalesOrderBundleSnapshot.objects.create(
        tenant=actor.tenant, order_item=order.items.get(), bundle_version=version,
        components_payload=[{"component_sku_id": first.pk, "quantity": 0 if invalid else 3}],
    )
    if country_mismatch:
        country.country_code = "TH"
        country.save(update_fields=["country_code"])
    if country_mismatch:
        with pytest.raises(ValueError, match="no_authorized_active_sales_store"):
            calculate_country(actor, country)
        return
    run = calculate_country(actor, country)
    if invalid:
        assert not run.entries.filter(entity_type="sku", entity_id=first.pk).exists()
        return
    entry = run.entries.get(entity_type="sku", entity_id=first.pk)
    assert entry.evidence["units_total"] == 6
    from zoneinfo import ZoneInfo
    assert entry.first_sale_date == order.paid_at_utc.astimezone(ZoneInfo(store.timezone)).date()
    assert (run.cutoff_date - entry.first_sale_date).days == 29
    assert entry.evidence["units_grade"] == "unavailable"
    assert entry.revenue == 0
    assert not run.entries.filter(entity_type="sku", entity_id=second.pk).exists()


def test_composite_run_persists_exact_sibling_and_bundle_evidence(abc_scope, monkeypatch):
    actor, country, store, spu, first, second = abc_scope
    tenant = actor.tenant
    _add_coverage(actor, store, upper=NOW + timedelta(days=5))
    sale(tenant, store, first, "mature-first", 40, 1)
    sale(tenant, store, second, "mature-second", 40, 1)
    order = sale(tenant, store, first, "siblings", 2, 8)
    SalesOrderItem.objects.create(
        sales_order=order, internal_sku=second, external_line_id="sibling", platform_product_id="shared",
        quantity=7, line_total_amount=14, currency=store.currency,
    )
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="PACK", product_type="bundle")
    bundle = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="PACK-1")
    bundle_order = sale(tenant, store, bundle, "bundle", 3, 2)
    version = ProductBundleVersion.objects.create(
        tenant=tenant, bundle_sku=bundle, version=1, created_by=actor,
        effective_at=bundle_order.created_at_utc - timedelta(days=1),
    )
    SalesOrderBundleSnapshot.objects.create(
        tenant=tenant, order_item=bundle_order.items.get(), bundle_version=version,
        components_payload=[{"component_sku_id": first.pk, "quantity": 3}],
    )
    later = ProductBundleVersion.objects.create(
        tenant=tenant, bundle_sku=bundle, version=2, created_by=actor, effective_at=NOW,
    )
    ProductBundleVersionComponent.objects.create(
        version=later, component_sku=first, component_sku_code=first.sku_code, quantity=50,
    )
    legacy = InventoryABCRun.objects.create(
        tenant=tenant, country=country, cutoff_date=NOW.date() - timedelta(days=2), status="ready",
    )
    legacy.entries.create(entity_type="spu", entity_id=spu.pk, grade="C", candidate_grade="A", candidate_streak=2)

    run = calculate_country(actor, country)
    assert run.status == "ready", run.issues
    assert run.config["classification_basis"] == "composite"
    assert run.config["policy_version"] == ABC_POLICY_VERSION
    first_entry = run.entries.get(entity_type="sku", entity_id=first.pk)
    second_entry = run.entries.get(entity_type="sku", entity_id=second.pk)
    parent_entry = run.entries.get(entity_type="spu", entity_id=spu.pk)
    assert first_entry.evidence["units_total"] == 15
    assert second_entry.evidence["units_total"] == 8
    assert parent_entry.evidence["units_total"] == 23
    assert parent_entry.evidence["max_single_order_units"] == "15"
    assert parent_entry.evidence["max_single_day_units"] == "15"
    assert parent_entry.evidence["active_weeks_last12"] == 2
    assert parent_entry.evidence["revenue_grade"] == parent_entry.evidence["units_grade"] == "A"
    assert parent_entry.evidence["policy_version"] == ABC_POLICY_VERSION
    assert parent_entry.revenue == Decimal("34")
    assert parent_entry.grade == "A"
    assert parent_entry.candidate_streak == 0
    assert run.entries.get(entity_type="sku", entity_id=bundle.pk).evidence["units_total"] == 2

    # The same cutoff may be retried, and legacy ready rows cannot seed its candidate streak.
    run.entries.filter(pk=parent_entry.pk).update(grade="B", candidate_grade="A", candidate_streak=1)
    same_cutoff = calculate_country(actor, country)
    repeated = same_cutoff.entries.get(entity_type="spu", entity_id=spu.pk)
    assert (repeated.grade, repeated.candidate_grade, repeated.candidate_streak) == ("B", "A", 1)
    settings, _ = InventoryObservationSettings.objects.get_or_create(tenant=tenant)

    # A changed threshold invalidates the old grade state; the new run adopts
    # its freshly computed grade immediately instead of carrying old streaks.
    InventoryABCEntry.objects.filter(run=same_cutoff, entity_type="spu", entity_id=spu.pk).update(
        grade="B", candidate_grade="A", candidate_streak=2,
    )
    settings.abc_a_percent = Decimal("81")
    settings.save(update_fields=["abc_a_percent"])
    monkeypatch.setattr(timezone, "now", lambda: NOW + timedelta(days=1))
    threshold_run = calculate_country(actor, country)
    threshold_entry = threshold_run.entries.get(entity_type="spu", entity_id=spu.pk)
    assert threshold_run.config["a_percent"] == "81.00"
    assert (threshold_entry.grade, threshold_entry.candidate_grade, threshold_entry.candidate_streak) == ("A", "", 0)

    # The same invalidation applies to the 90-to-60-day window change.
    InventoryABCEntry.objects.filter(run=threshold_run, entity_type="spu", entity_id=spu.pk).update(
        grade="B", candidate_grade="A", candidate_streak=2,
    )
    settings.abc_window_days = 60
    settings.save(update_fields=["abc_window_days"])
    monkeypatch.setattr(timezone, "now", lambda: NOW + timedelta(days=2))
    window_run = calculate_country(actor, country)
    window_entry = window_run.entries.get(entity_type="spu", entity_id=spu.pk)
    assert window_run.config["window_days"] == 60
    assert (window_entry.grade, window_entry.candidate_grade, window_entry.candidate_streak) == ("A", "", 0)

    # With an unchanged basis, the normal consecutive-day debounce remains active.
    InventoryABCEntry.objects.filter(run=window_run, entity_type="spu", entity_id=spu.pk).update(
        grade="B", candidate_grade="", candidate_streak=0,
    )
    monkeypatch.setattr(timezone, "now", lambda: NOW + timedelta(days=3))
    debounced_run = calculate_country(actor, country)
    debounced = debounced_run.entries.get(entity_type="spu", entity_id=spu.pk)
    assert (debounced.grade, debounced.candidate_grade, debounced.candidate_streak) == ("B", "A", 1)
    # Same-day retries preserve the already persisted transition state.
    retry = calculate_country(actor, country).entries.get(entity_type="spu", entity_id=spu.pk)
    assert (retry.grade, retry.candidate_grade, retry.candidate_streak) == ("B", "A", 1)


def test_legacy_ready_snapshot_is_pending_then_partial_is_reference_only(abc_scope):
    actor, country, store, spu, first, _ = abc_scope
    tenant = actor.tenant
    legacy = InventoryABCRun.objects.create(
        tenant=tenant, country=country, cutoff_date=NOW.date() - timedelta(days=1), status="ready",
        config={"classification_basis": "composite", "policy_version": "retired"},
    )
    legacy.entries.create(entity_type="sku", entity_id=first.pk, grade="C")
    row = {"sku_id": first.pk, "spu_id": spu.pk}
    with CaptureQueriesContext(connection) as queries:
        pending = decorate_rows(actor, country, [row])
    assert len(queries) == 2
    assert pending["status"] == "pending" and pending["composite_pending"]
    assert row["abc"]["run_id"] is None
    assert row["abc"]["sku_grade"] == "unavailable"
    assert row["abc"]["sku_evidence"] == {}
    assert not filter_skus(actor, country, ProductSKU.objects.filter(tenant=tenant), "C").exists()

    sale(tenant, store, first, "partial", 40, 4)
    run = calculate_country(actor, country)
    assert run.status == "partial"
    assert run.entries.get(entity_type="sku", entity_id=first.pk).candidate_streak == 0
    with CaptureQueriesContext(connection) as queries:
        meta = decorate_rows(actor, country, [row])
    assert len(queries) == 4
    assert not any("sales_order" in query["sql"].lower() for query in queries)
    assert meta["run_id"] == run.pk
    assert row["abc"]["policy_version"] == ABC_POLICY_VERSION
    assert row["abc"]["sku_grade"] == "unavailable"
    assert row["abc"]["sku_reference_grade"] == "A"
    assert row["abc"]["sku_evidence"]["history_complete"] is False
    assert list(filter_skus(actor, country, ProductSKU.objects.filter(tenant=tenant), "A")) == [first]

    ready = InventoryABCRun.objects.create(
        tenant=tenant, country=country, cutoff_date=run.cutoff_date - timedelta(days=1),
        status="ready", config=run.config,
    )
    selected, metadata = published_run(actor, country)
    assert selected == ready
    assert metadata["latest_status"] == "ready"


def test_database_defaults_evidence_for_old_image_insert(abc_scope):
    actor, country, _, _, first, _ = abc_scope
    run = InventoryABCRun.objects.create(
        tenant=actor.tenant, country=country, cutoff_date=NOW.date() - timedelta(days=1),
    )
    table = connection.ops.quote_name(InventoryABCEntry._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (run_id, entity_type, entity_id, grade, candidate_grade, candidate_streak) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [run.pk, "sku", first.pk, "A", "", 0],
        )
    assert run.entries.get().evidence == {}




@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("older", [False, True])
def test_new_pending_run_remains_visible_with_existing_ready(abc_scope, marked, older):
    actor, country, *_ = abc_scope
    policy = {"classification_basis": "composite", "policy_version": ABC_POLICY_VERSION}
    ready = InventoryABCRun.objects.create(tenant=actor.tenant, country=country, cutoff_date=NOW.date(), status="ready", config=policy)
    pending = InventoryABCRun.objects.create(tenant=actor.tenant, country=country, cutoff_date=NOW.date(), status="queued", config=policy if marked else {"source": "automatic"})
    if older:
        InventoryABCRun.objects.filter(pk=pending.pk).update(created_at=ready.created_at - timedelta(days=1))
    selected, meta = published_run(actor, country)
    assert selected == ready
    assert meta["latest_status"] == "queued"
    assert meta["run_id"] == ready.pk
