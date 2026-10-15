"""No database or broker: verify legacy relay fences and failure preservation."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.integrations.tasks import run_readonly_sync_job


@pytest.mark.parametrize("queue,sequence,failed", [("sync", 3, False), ("celery", 0, False), ("sync", 2, True)])
def test_relay_preserves_continuation_fence_and_retries_without_provider(queue, sequence, failed):
    segment = SimpleNamespace(batch=SimpleNamespace(status="running"))
    run = SimpleNamespace(history_segment_id=11, history_segment=segment, status="queued",
                          masked_log={"runtime_budget": {"sequence": sequence}})
    with patch("apps.integrations.tasks.SyncJob.objects") as jobs, \
         patch("apps.integrations.tasks.SyncRun.objects") as runs, \
         patch("apps.common.module_gate.is_module_enabled", return_value=True), \
         patch("apps.integrations.history_sync.history_execution_allowed", return_value=True), \
         patch.object(run_readonly_sync_job, "apply_async", side_effect=RuntimeError("synthetic broker failure") if failed else None) as relay, \
         patch.object(run_readonly_sync_job, "retry", return_value=RuntimeError("retry without fetching")) as retry, \
         patch("apps.integrations.tasks.run_sync_job") as provider:
        jobs.select_related.return_value.get.return_value = SimpleNamespace(pk=7)
        runs.filter.return_value.first.return_value = run
        run_readonly_sync_job.push_request(delivery_info={"routing_key": queue})
        try:
            if failed:
                with pytest.raises(RuntimeError, match="retry without fetching"):
                    run_readonly_sync_job.run(7, "existing-durable-key", sequence)
            else:
                result = run_readonly_sync_job.run(7, "existing-durable-key", sequence)
                assert result["status"] == "rerouted"
        finally:
            run_readonly_sync_job.pop_request()
        assert relay.call_args.kwargs["kwargs"] == {"idempotency_key": "existing-durable-key", "resume_sequence": sequence}
        assert relay.call_args.kwargs["queue"] == "sync-history"
        assert run.status == "queued"
        provider.assert_not_called()
        runs.create.assert_not_called()
        assert retry.call_count == int(failed)
