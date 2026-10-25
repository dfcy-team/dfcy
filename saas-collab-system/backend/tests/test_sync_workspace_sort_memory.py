from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.integrations.workspace_service import integration_workspace
from tests.test_sync_workspace_pagination import NOW, add_run, workspace

pytestmark = pytest.mark.django_db


def test_last_success_preserves_null_timestamp_and_pk_tie_order(workspace):
    user, job = workspace
    old_success = add_run(job, 1, enqueued_at=None, started_at=None, finished_at=NOW + timedelta(days=5))
    null_enqueued = add_run(job, 2, enqueued_at=None, started_at=NOW, finished_at=NOW + timedelta(days=4))
    later_enqueue = add_run(job, 3, enqueued_at=NOW, started_at=None, finished_at=NOW + timedelta(days=1))
    winner = add_run(job, 4, enqueued_at=NOW, started_at=None, finished_at=None)
    add_run(job, 5, enqueued_at=NOW + timedelta(days=1), status="failed", finished_at=NOW + timedelta(days=8))
    add_run(job, 6, enqueued_at=NOW + timedelta(days=2), masked_log={"execution_mode": "simulation"}, finished_at=NOW + timedelta(days=9))
    add_run(job, 7, enqueued_at=NOW + timedelta(days=3), error_code="SYNC_INVALID_QUEUE_ARCHIVED", finished_at=NOW + timedelta(days=10))

    row = integration_workspace(user, "sync-jobs", {})["results"][0]
    assert row["last_success_at"] is None  # winner follows enqueue/start/id ordering, not MAX(finished_at)
    assert winner.pk > later_enqueue.pk > null_enqueued.pk > old_success.pk


def test_large_log_page_and_last_success_queries_have_no_run_sort(workspace):
    user, job = workspace
    large_log = {"execution_mode": "live_readonly", "payload": "x" * (365 * 1024)}
    add_run(job, 1, masked_log=large_log)

    for mode in ("sync-runs", "sync-jobs"):
        with CaptureQueriesContext(connection) as captured:
            result = integration_workspace(user, mode, {"page_size": 1})
        assert result["results"]
        selects = [q["sql"] for q in captured if q["sql"].lstrip().upper().startswith("SELECT")]
        quote_name = connection.ops.quote_name
        run_table = quote_name("integrations_syncrun")
        run_id = f"{run_table}.{quote_name('id')}"
        masked_log = f"{run_table}.{quote_name('masked_log')}"
        detail_queries = [sql for sql in selects
                          if sql.startswith(f"SELECT {run_id},")
                          and masked_log in sql.split(" FROM ", 1)[0]]
        assert detail_queries
        assert all("ORDER BY" not in sql.upper() for sql in detail_queries), [sql[-1600:] for sql in detail_queries if "ORDER BY" in sql.upper()]
        finished_at = quote_name("finished_at")
        sync_job_id = quote_name("sync_job_id")
        success_queries = [sql for sql in selects
                           if finished_at in sql.split(" FROM ", 1)[0]
                           and sync_job_id in sql.split(" FROM ", 1)[0]
                           and quote_name("masked_log") not in sql.split(" FROM ", 1)[0]
                           and "live_readonly" in sql]
        assert success_queries
        assert all("ORDER BY" not in sql.upper() for sql in success_queries)
