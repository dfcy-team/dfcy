from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser
from apps.integrations.models import PlatformIntegrationConfig, SyncCursor, SyncJob, SyncRun
from apps.sales_management.serializers import SyncSourceSerializer
from apps.sales_management.views import annotate_sync_source_details
from apps.tenants.models import Tenant


def make_source(tenant, index):
    user = CustomUser.objects.create_user(
        username=f"sync-source-user-{index}", tenant=tenant, user_type=CustomUser.UserType.INTERNAL,
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="shopee", account_alias=f"store-{index}", created_by=user,
    )
    return SyncJob.objects.create(
        tenant=tenant, integration_config=config, resource_type=SyncJob.ResourceType.SALES_ORDER,
    )


def make_run(job, index, *, status, started_at, finished_at=None, fetched_count=0, error_code=""):
    return SyncRun.objects.create(
        tenant=job.tenant,
        sync_job=job,
        run_id=f"run-{index}",
        idempotency_key=f"key-{index}",
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        fetched_count=fetched_count,
        error_code=error_code,
    )


@pytest.mark.django_db
def test_sync_source_summary_preserves_no_run_failure_success_and_cursor_semantics():
    tenant = Tenant.objects.create(name="Quality source summary", code="quality-source-summary")
    no_run = make_source(tenant, 1)
    SyncCursor.objects.create(tenant=tenant, sync_job=no_run, cursor_key="z", cursor_value="last")
    SyncCursor.objects.create(tenant=tenant, sync_job=no_run, cursor_key="a", cursor_value="first")

    failed = make_source(tenant, 2)
    older_success_at = datetime(2026, 1, 1, tzinfo=UTC)
    make_run(
        failed, "2-old-success", status=SyncRun.Status.SUCCESS,
        started_at=older_success_at, finished_at=older_success_at, fetched_count=4,
    )
    make_run(
        failed, "2-failed", status=SyncRun.Status.FAILED,
        started_at=datetime(2026, 2, 1, tzinfo=UTC), finished_at=datetime(2026, 2, 1, tzinfo=UTC),
        fetched_count=7, error_code="API_TIMEOUT",
    )
    SyncCursor.objects.create(tenant=tenant, sync_job=failed, cursor_key="daily", cursor_value="2026-02-01")

    successful = make_source(tenant, 3)
    successful_at = datetime(2026, 3, 1, tzinfo=UTC)
    make_run(
        successful, "3-success", status=SyncRun.Status.SUCCESS,
        started_at=successful_at, finished_at=successful_at, fetched_count=12,
    )

    rows = annotate_sync_source_details(
        SyncJob.objects.filter(id__in=[no_run.id, failed.id, successful.id]).select_related("integration_config")
    )
    serialized = {row["id"]: row for row in SyncSourceSerializer(rows, many=True).data}

    assert serialized[no_run.id]["run_status"] == SyncJob.Status.IDLE
    assert serialized[no_run.id]["last_success_at"] is None
    assert serialized[no_run.id]["fetched_count"] == 0
    assert serialized[no_run.id]["sync_cursor"] == "first"
    assert serialized[no_run.id]["error_summary"] == ""

    assert serialized[failed.id]["run_status"] == SyncRun.Status.FAILED
    assert serialized[failed.id]["last_success_at"] == older_success_at
    assert serialized[failed.id]["fetched_count"] == 7
    assert serialized[failed.id]["sync_cursor"] == "2026-02-01"
    assert serialized[failed.id]["error_summary"] == "API_TIMEOUT"

    assert serialized[successful.id]["run_status"] == SyncRun.Status.SUCCESS
    assert serialized[successful.id]["last_success_at"] == successful_at
    assert serialized[successful.id]["fetched_count"] == 12
    assert serialized[successful.id]["error_summary"] == ""


@pytest.mark.django_db
def test_sync_source_serialization_query_count_is_independent_of_source_count():
    tenant = Tenant.objects.create(name="Quality source query count", code="quality-source-query-count")
    sources = [make_source(tenant, index) for index in range(20)]

    def query_count(source_ids):
        rows = annotate_sync_source_details(
            SyncJob.objects.filter(id__in=source_ids).select_related("integration_config")
        )
        with CaptureQueriesContext(connection) as queries:
            SyncSourceSerializer(rows, many=True).data
        return len(queries)

    one_source_query_count = query_count([sources[0].id])
    twenty_source_query_count = query_count([source.id for source in sources])

    assert one_source_query_count == 1
    assert twenty_source_query_count == one_source_query_count
