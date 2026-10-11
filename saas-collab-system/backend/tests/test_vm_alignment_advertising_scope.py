from types import SimpleNamespace
from unittest.mock import patch

from apps.integrations.sync_policy import resolve_job_scope


def test_aligned_policy_preserves_advertising_authorization_and_scope():
    authorization = SimpleNamespace(region="TH")
    config = SimpleNamespace(platform="shopee")
    job = SimpleNamespace(
        integration_config=config, resource_type="advertising_report",
        sync_scope={"query": {"lookback_days": 7}}, store_authorization=authorization,
        tenant_id=1, integration_config_id=2, store_authorization_id=3,
        warehouse_authorization_id=None,
    )
    resolved = {"report_timezone": "Asia/Bangkok", "advertising_datasets": ["shop_hourly"]}
    with patch("apps.integrations.readonly_clients.default_sync_scope", return_value=resolved) as scope:
        with patch("apps.integrations.sync_policy._source_key", return_value="non-secret-source"):
            result = resolve_job_scope(job)
    scope.assert_called_once_with(config, job.sync_scope, "advertising_report", authorization)
    assert result["report_timezone"] == "Asia/Bangkok"
    assert result["advertising_datasets"] == ["shop_hourly"]
