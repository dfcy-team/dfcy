from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.reports.analysis_jobs import authorization_key, run_analysis
from apps.reports.async_exports import export_fingerprint, run_export
from apps.reports.models import ReportAnalysisJob
from tests.test_sales_management import client_for, create_scope, grant, user_for


@pytest.mark.django_db(transaction=True)
def test_cancelled_active_workers_still_consume_submission_quota_for_both_endpoints():
    tenant, _, _, _ = create_scope("cancel-quota")
    user = user_for(tenant, "cancel-quota-user")
    for permission in ("reports.view", "sales_management.view", "reports.export", "replenishment.view"):
        grant(user, permission)
    now = timezone.now()
    analysis_config = {"dataset": "sales", "mode": "monthly", "year": 2026, "filters": {}, "cutoff": "2026-10-15"}
    analysis_fp = authorization_key(user, analysis_config)
    export_config, export_fp = export_fingerprint(user, "replenishment", {})
    for config, fingerprint in [(analysis_config, analysis_fp)] * 3 + [(export_config, export_fp)] * 3:
        ReportAnalysisJob.objects.create(
            tenant=tenant, requested_by=user, config=config, fingerprint=fingerprint,
            status="cancelled", worker_active=True, expires_at=now + timedelta(minutes=15),
        )

    client = client_for(user)
    analysis = client.post("/api/report/analysis-jobs/", {"dataset": "sales", "year": 2026}, format="json")
    export = client.post("/api/report/export-jobs/", {"report_type": "replenishment"}, format="json")
    assert analysis.status_code == 429
    assert export.status_code == 429


@pytest.mark.django_db(transaction=True)
def test_cancel_during_month_block_stops_later_blocks_and_worker_releases_quota():
    tenant, _, _, _ = create_scope("cancel-month-block")
    user = user_for(tenant, "cancel-month-user")
    grant(user, "reports.view")
    grant(user, "sales_management.view")
    config = {"dataset": "sales", "mode": "period", "date_from": "2026-01-01", "date_to": "2026-03-31", "filters": {}, "cutoff": "2026-10-15"}
    job = ReportAnalysisJob.objects.create(
        tenant=tenant, requested_by=user, config=config, fingerprint=authorization_key(user, config),
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    queries = []

    def query_dataset(request, block, limit):
        queries.append(block["filters"]["date_from"])
        ReportAnalysisJob.objects.filter(pk=job.pk).update(status="cancelled")
        return {"rows": [], "dimension_labels": {}, "cached": False, "truncated": False,
                "computed_at": timezone.now(), "refreshed_at": None, "metric_version": "v1", "note": ""}

    from apps.reports.aggregate_blocks import daily_blocks

    with patch("apps.reports.analysis_jobs.build_analysis", side_effect=lambda request, cfg: daily_blocks(request, {
        "dataset": "sales", "dimensions": ["date", "currency"], "metrics": [],
        "filters": {"date_from": "2026-01-01", "date_to": "2026-03-31"},
    })), patch("apps.reports.aggregate_blocks.query_dataset", side_effect=query_dataset):
        run_analysis(job.pk)

    job.refresh_from_db()
    assert queries == ["2026-01-01"]
    assert job.status == "cancelled"
    assert job.worker_active is False


@pytest.mark.django_db
def test_cancelled_queued_analysis_and_export_are_not_claimed():
    tenant, _, _, _ = create_scope("cancel-queued")
    user = user_for(tenant, "cancel-queued-user")
    config = {"dataset": "sales", "mode": "monthly", "year": 2026, "filters": {}, "cutoff": "2026-10-15"}
    analysis = ReportAnalysisJob.objects.create(
        tenant=tenant, requested_by=user, config=config, fingerprint="a" * 64,
        status="cancelled", expires_at=timezone.now() + timedelta(minutes=15),
    )
    export_config, export_fp = export_fingerprint(user, "replenishment", {})
    export = ReportAnalysisJob.objects.create(
        tenant=tenant, requested_by=user, config=export_config, fingerprint=export_fp,
        status="cancelled", expires_at=timezone.now() + timedelta(minutes=15),
    )
    with patch("apps.reports.analysis_jobs.build_analysis") as build_analysis, patch(
        "apps.reports.async_exports.create_export_request"
    ) as create_export:
        run_analysis(analysis.pk)
        run_export(export.pk)
    analysis.refresh_from_db()
    export.refresh_from_db()
    assert not analysis.worker_active and not export.worker_active
    build_analysis.assert_not_called()
    create_export.assert_not_called()
