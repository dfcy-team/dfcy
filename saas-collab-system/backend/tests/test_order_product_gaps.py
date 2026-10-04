from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.integrations.adapters import MarketplaceProductAdapter
from apps.integrations.models import ConnectionCapability, SyncCheckpoint, SyncCursor, SyncJob, SyncRun
from apps.integrations.order_product_gaps import (
    gap_candidates, gap_cursor, gap_report, gap_summary, parse_gap_cursor, source_watermark,
)
from apps.integrations.platform_product_ingestion import upsert_platform_product
from apps.integrations.readonly_clients import default_sync_scope
from apps.integrations.sync_services import run_sync_job
from apps.listings.models import PlatformProductDetail
from tests.test_platform_product_ingestion import _fixture
from tests.test_phase2_sync_framework import (
    authenticated_client, grant_integration_access, grant_integration_view_only,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def context():
    c = _fixture(create_store_mapping_row=False)
    order_job = c["job"]
    c["source_run"] = SyncRun.objects.create(tenant=c["tenant"], sync_job=order_job,
        run_id="order-source", idempotency_key="order-source", status="success")
    c["product_job"] = SyncJob.objects.create(tenant=c["tenant"], integration_config=c["config"],
        store_authorization=c["authorization"], resource_type="platform_product",
        sync_scope={"query": {"product_order_backfill": "order_missing_only", "page_size": 1}})
    ConnectionCapability.objects.create(authorization=c["authorization"], capability_code="PRODUCT",
        read_enabled=True, write_enabled=False, status="active")
    return c


def sold(c, product, variant, *, line="line", run=None, store=None):
    instant = datetime(2025, 1, 1, tzinfo=UTC)
    order = SalesOrder.objects.create(tenant=c["tenant"], platform=c["platform"], store=store or c["store"],
        authorization=c["config"], source_run=run or c["source_run"], external_order_id=line,
        raw_status="COMPLETED", normalized_status="completed", status_mapping_version="fixture",
        created_at_utc=instant, updated_at_utc=instant, business_date=instant.date(), currency="MYR", payload_hash="a" * 64)
    return SalesOrderItem.objects.create(sales_order=order, external_line_id=line,
        platform_product_id=product, platform_variant_id=variant, quantity=1, currency="MYR")


def catalogue(c, product, variant, **values):
    return PlatformProductDetail.objects.create(tenant=c["tenant"], platform=c["platform"], store=c["store"],
        platform_product_id=product, platform_variant_id=variant, **values)


class Upstream:
    def __init__(self, unavailable=()):
        self.calls, self.unavailable = [], set(unavailable)

    def preflight(self):
        pass

    def fetch_products(self, cursor, scope):
        self.calls.append(("catalogue", str(cursor or "")))
        return {"records": [], "next_cursor": ""}

    def fetch_products_by_ids(self, ids):
        self.calls.append(("target", list(ids)))
        return {"records": [{"platform_product_id": value, "platform_variant_id": value + "1",
            "platform_sku": "SELLER", "title": "Provider fact", "sales_status": "UNLIST"}
            for value in ids if value not in self.unavailable],
            "raw_responses": [], "unavailable_item_ids": [value for value in ids if value in self.unavailable]}


def test_exact_relation_counts_normalizes_zero_without_touching_orders(context):
    c, job = context, context["product_job"]
    zero = sold(c, "100", "0", line="zero")
    sold(c, "100", "101", line="model")
    sold(c, "200", "201", line="missing")
    sold(c, "300", "301", line="variant")
    sold(c, "400", "401", line="conflict")
    sold(c, "broken", "501", line="invalid")
    catalogue(c, "100", "100")
    catalogue(c, "100", "101")
    catalogue(c, "300", "302")
    catalogue(c, "999", "401")
    report = gap_report(job)
    assert report["summary"] == {"source_rows": 6, "unique_pairs": 6, "linked_pairs": 2,
        "missing_pairs": 4, "missing_product_ids": 1, "missing_variant_pairs": 1,
        "conflict_pairs": 1, "invalid_pairs": 1, "zero_variant_pairs": 1, "watermark": source_watermark(job)}
    assert {row["reason"] for row in report["samples"]} == {
        "product_missing", "variant_missing", "identity_conflict", "invalid_identity"}
    assert gap_candidates(job, report["summary"]["watermark"]) == (["200", "300"], False)
    zero.refresh_from_db()
    assert zero.platform_variant_id == "0" and zero.internal_sku_id is None


def test_empty_source_and_bounded_sample(context):
    job = context["product_job"]
    assert gap_report(job)["summary"]["source_rows"] == 0
    for i in range(25):
        sold(context, str(100 + i), str(100 + i) + "1", line=f"line-{i}")
    report = gap_report(job)
    assert report["summary"]["missing_pairs"] == 25 and len(report["samples"]) == 20
    ids, more = gap_candidates(job, report["summary"]["watermark"], limit=2)
    assert ids == ["100", "101"] and more


def test_report_reuses_one_classification_and_all_linked_has_no_sample(context, django_assert_num_queries):
    job = context["product_job"]
    gap_report(job)  # Resolve related-object caches before measuring SQL.
    sold(context, "100", "101")
    catalogue(context, "100", "101")
    with django_assert_num_queries(2):
        report = gap_report(job)
    assert report["summary"]["source_rows"] == report["summary"]["linked_pairs"] == 1
    assert report["summary"]["missing_pairs"] == 0 and report["samples"] == []


def test_conflict_and_invalid_only_do_not_enter_targeted_phase(context):
    job = context["product_job"]
    job.sync_scope = {"query": {"product_order_backfill": "catalog_and_order_missing"}}
    job.save(update_fields=["sync_scope"])
    sold(context, "100", "101", line="conflict")
    catalogue(context, "999", "101")
    sold(context, "broken", "501", line="invalid")
    upstream = Upstream()
    run, _ = run_sync_job(job, adapter=MarketplaceProductAdapter(context["config"], client=upstream), idempotency_key="conflict-only")
    assert upstream.calls == [("catalogue", "")]
    assert run.status == "success"
    assert run.masked_log["order_product_reconciliation"]["before"]["missing_pairs"] == 2
    assert run.masked_log["order_product_reconciliation"]["after"]["conflict_pairs"] == 1


def test_same_store_environment_and_source_resource_are_required(context):
    from apps.masterdata.models import StoreMaster
    c = context
    other = StoreMaster.objects.create(tenant=c["tenant"], platform=c["platform"], code="other", name="Other", currency="MYR")
    sold(c, "100", "101", line="other-store", store=other)
    wrong = SyncRun.objects.create(tenant=c["tenant"], sync_job=c["product_job"],
        run_id="wrong-source", idempotency_key="wrong", status="success")
    # Inject one inconsistent source via SQL to prove the
    # query excludes an inconsistent fact rather than trusting the snapshot.
    order = sold(c, "200", "201", line="valid")
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("UPDATE sales_order SET source_run_id=%s WHERE id=%s", [wrong.id, order.sales_order_id])
    assert gap_report(c["product_job"])["summary"]["source_rows"] == 0
    c["config"].environment = "production"
    c["config"].save(update_fields=["environment"])
    # Both the job and orders now resolve the same config environment.
    SalesOrder.objects.filter(pk=order.sales_order_id).update(source_run=c["source_run"])
    assert gap_report(c["product_job"])["summary"]["source_rows"] == 1


def test_watermark_excludes_new_orders_and_cursor_is_bounded(context):
    job = context["product_job"]
    sold(context, "100", "101", line="first")
    watermark = source_watermark(job)
    sold(context, "200", "201", line="later")
    assert gap_candidates(job, watermark)[0] == ["100"]
    assert parse_gap_cursor(gap_cursor(watermark, "100")) == (watermark, "100")
    assert len(gap_cursor(watermark, "9" * 20)) < 255


@pytest.mark.parametrize("cursor", ["12", "order-gap:v1:no:100", "order-gap:v1:1:other", "order-gap:v1:1:1:2"])
def test_invalid_cursor_fails_closed(cursor):
    with pytest.raises(ValidationError):
        parse_gap_cursor(cursor)


def test_targeted_run_fills_real_products_and_validates_remaining_omission(context):
    c, job = context, context["product_job"]
    first = sold(c, "100", "1001", line="first")
    sold(c, "200", "2001", line="unavailable")
    conflict = catalogue(c, "999", "3001", title="Protected")
    sold(c, "300", "3001", line="conflict")
    upstream = Upstream(unavailable={"200"})
    run, created = run_sync_job(job, adapter=MarketplaceProductAdapter(c["config"], client=upstream), idempotency_key="target")
    assert created and run.status == "success", run.masked_error_message
    progress = run.masked_log["order_product_reconciliation"]
    assert progress["before"]["missing_pairs"] == 3
    assert progress["after"]["missing_pairs"] == 2
    assert progress["attempted_products"] == 2 and progress["unavailable_products"] == 1
    assert progress["coverage_certified"] is False and progress["after"]["conflict_pairs"] == 1
    assert upstream.calls == [("target", ["100"]), ("target", ["200"])]
    first.refresh_from_db()
    conflict.refresh_from_db()
    assert first.internal_sku_id is None and conflict.platform_product_id == "999" and conflict.title == "Protected"
    assert PlatformProductDetail.objects.filter(store=c["store"], platform_product_id="100", platform_variant_id="1001").exists()
    assert SyncCheckpoint.objects.get(sync_job=job).cursor_json == {"default": ""}


def test_normal_then_targeted_and_catalog_only_are_distinct(context):
    c, job = context, context["product_job"]
    sold(c, "100", "1001")
    for mode, expected in [("catalog_only", [("catalogue", "")]),
                           ("catalog_and_order_missing", [("catalogue", ""), ("target", ["100"])])]:
        job.sync_scope = {"query": {"product_order_backfill": mode}}
        job.save(update_fields=["sync_scope"])
        upstream = Upstream()
        run, _ = run_sync_job(job, adapter=MarketplaceProductAdapter(c["config"], client=upstream), idempotency_key=mode)
        assert run.status == "success", run.masked_error_message
        assert upstream.calls == expected


def test_sliced_targeted_run_keeps_watermark_run_counts_and_does_not_replay(context):
    c, job = context, context["product_job"]
    sold(c, "100", "1001", line="first")
    sold(c, "200", "2001", line="second")
    watermark = source_watermark(job)
    job.sync_scope["schedule"] = {"execution_budget_seconds": 60}
    job.save(update_fields=["sync_scope"])
    upstream = Upstream()
    with patch("apps.integrations.sync_services.monotonic", side_effect=[0, 61]):
        first, _ = run_sync_job(job, adapter=MarketplaceProductAdapter(c["config"], client=upstream), idempotency_key="slice")
    first.refresh_from_db()
    assert first.status == "queued" and first.created_count == 1
    assert SyncCursor.objects.get(sync_job=job).cursor_value == gap_cursor(watermark, "100")
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()
    sold(c, "300", "3001", line="arrived-during-pass")
    job.refresh_from_db()
    with patch("apps.integrations.sync_services.monotonic", return_value=0):
        final, _ = run_sync_job(job, adapter=MarketplaceProductAdapter(c["config"], client=upstream),
            idempotency_key="slice", resume_sequence=1)
    final.refresh_from_db()
    assert final.pk == first.pk and final.run_id == first.run_id and final.status == "success"
    assert final.fetched_count == final.created_count == 2
    assert final.masked_log["order_product_reconciliation"]["attempted_products"] == 2
    assert final.masked_log["order_product_reconciliation"]["after"]["missing_pairs"] == 0
    assert upstream.calls == [("target", ["100"]), ("target", ["200"])]
    assert gap_report(job)["summary"]["missing_pairs"] == 1


def test_targeted_ingestion_never_reparents_even_unmapped_variant(context):
    c = context
    row = catalogue(c, "999", "1001", title="Protected", platform_sku="unchanged")
    result = upsert_platform_product(c["product_job"], {"store_id": c["store"].id,
        "platform_product_id": "100", "platform_variant_id": "1001", "title": "Overwrite",
        "order_identity_backfill": True})
    row.refresh_from_db()
    assert result["result_code"] == "ORDER_PRODUCT_IDENTITY_CONFLICT" and result["action"] == "skipped"
    assert row.platform_product_id == "999" and row.title == "Protected" and row.platform_sku == "unchanged"


@pytest.mark.parametrize("mode", ["catalog_only", "catalog_and_order_missing"])
def test_normal_catalogue_cannot_bypass_parent_identity_protection(context, mode):
    c, job = context, context["product_job"]
    row = catalogue(c, "999", "1001", title="Protected")
    sold(c, "100", "1001")
    job.sync_scope = {"query": {"product_order_backfill": mode}}
    job.save(update_fields=["sync_scope"])
    upstream = Upstream()
    upstream.fetch_products = lambda cursor, scope: {"records": [{
        "platform_product_id": "100", "platform_variant_id": "1001", "title": "Overwrite",
    }], "next_cursor": ""}
    run, _ = run_sync_job(job, adapter=MarketplaceProductAdapter(c["config"], client=upstream), idempotency_key="normal-conflict")
    assert run.status == "success" and run.skipped_count == 1
    row.refresh_from_db()
    assert row.platform_product_id == "999" and row.title == "Protected"
    assert not upstream.calls
    if mode == "catalog_and_order_missing":
        assert run.masked_log["order_product_reconciliation"]["after"]["conflict_pairs"] == 1


def test_before_is_post_catalogue_and_no_redundant_target_call_if_last_page_resolved_gap(context):
    c, job = context, context["product_job"]
    sold(c, "100", "1001")
    job.sync_scope = {"query": {"product_order_backfill": "catalog_and_order_missing"}}
    job.save(update_fields=["sync_scope"])
    upstream = Upstream()
    upstream.fetch_products = lambda cursor, scope: {"records": [{
        "platform_product_id": "100", "platform_variant_id": "1001", "title": "Real provider fact",
    }], "next_cursor": ""}
    run, _ = run_sync_job(job, adapter=MarketplaceProductAdapter(c["config"], client=upstream), idempotency_key="already-filled")
    assert run.status == "success" and not upstream.calls
    progress = run.masked_log["order_product_reconciliation"]
    assert progress["before"]["missing_pairs"] == progress["after"]["missing_pairs"] == 0
    assert run.raw_envelopes.count() == 1


def test_readonly_preview_and_policy_update_have_separate_permissions_and_no_execution(context):
    c, job = context, context["product_job"]
    grant_integration_view_only(c["user"])
    client = authenticated_client(c["user"])
    endpoint = f"/api/internal/integrations/sync-jobs/{job.id}/"
    sold(c, "100", "1001")
    with patch("apps.integrations.adapters.ShopeeReadonlyClient") as provider:
        result = client.get(endpoint + "product-gaps/")
        assert result.status_code == 200 and result.data["data"]["summary"]["missing_pairs"] == 1
        provider.assert_not_called()
    assert client.patch(endpoint, {"product_order_backfill": "catalog_only"}, format="json").status_code == 403
    assert client.get(endpoint + "product-gaps/?store_id=999").status_code == 400
    assert job.runs.count() == job.cursors.count() == 0


def test_policy_save_resets_only_query_cursor_and_never_enables_or_runs(context):
    c, job = context, context["product_job"]
    grant_integration_access(c["user"])
    job.is_enabled = False
    job.save(update_fields=["is_enabled"])
    SyncCursor.objects.create(tenant=c["tenant"], sync_job=job, cursor_key="default", cursor_value="old")
    client = authenticated_client(c["user"])
    response = client.patch(f"/api/internal/integrations/sync-jobs/{job.id}/",
        {"product_order_backfill": "catalog_and_order_missing"}, format="json")
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.sync_scope["query"]["product_order_backfill"] == "catalog_and_order_missing"
    assert not job.is_enabled and job.cursors.get(cursor_key="default").cursor_value == "" and job.runs.count() == 0


def test_policy_rejects_non_shopee_or_non_product_jobs(context):
    c = context
    grant_integration_access(c["user"])
    client = authenticated_client(c["user"])
    response = client.patch(f'/api/internal/integrations/sync-jobs/{c["job"].id}/',
        {"product_order_backfill": "order_missing_only"}, format="json")
    assert response.status_code == 400
    assert client.get(f'/api/internal/integrations/sync-jobs/{c["job"].id}/product-gaps/').status_code == 400


def test_missing_only_ignores_time_range_and_normal_full_sync_remains_default(context):
    scope = default_sync_scope(context["config"], {"product_full_sync": False,
        "query": {"product_order_backfill": "order_missing_only", "mode": "range", "start_at": "broken", "end_at": "broken"}}, "platform_product")
    assert scope["product_order_backfill"] == "order_missing_only"
    assert default_sync_scope(context["config"], {}, "platform_product")["product_order_backfill"] == "catalog_and_order_missing"
