"""Offline replay and no-repeat-exchange guarantees for the V518 cloud merge."""
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import DatabaseError
from django.utils import timezone
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from rest_framework.exceptions import ValidationError


def test_real_graph_plans_only_unapplied_integration_branch():
    loader = MigrationLoader(None)
    graph = loader.graph
    recovery = ("integrations", "0068_automatic_refresh_commit_recovery")
    warehouse = ("integrations", "0068_merge_warehouse_order_jobs")
    change = ("integrations", "0069_alter_syncjob_resource_type")
    leaves = graph.leaf_nodes("integrations")
    assert len(leaves) == 1
    assert {recovery, warehouse, change} <= set(graph.forwards_plan(leaves[0]))
    # Actual Django planner; in-memory journal, never a production connection.
    loader.applied_migrations = dict.fromkeys(
        set(graph.forwards_plan(recovery)) | set(graph.forwards_plan(warehouse))
    )
    executor = object.__new__(MigrationExecutor)
    executor.loader = loader
    plan = executor.migration_plan(leaves)
    assert all(not backwards for _, backwards in plan)
    nodes = [(migration.app_label, migration.name) for migration, _ in plan]
    assert recovery not in nodes and warehouse not in nodes
    assert change in nodes and leaves[0] in nodes


def test_pending_recovery_never_reissues_exchange_without_receipt(monkeypatch):
    from apps.integrations import automatic_refresh, marketplace_oauth_service
    from apps.integrations import refresh_commit_recovery as service

    attempt = SimpleNamespace(pk="attempt1", commit_recovery={
        "schema": 1, "scope": "bound", "operation_id": "automatic-refresh:attempt1",
        "recover_only": True,
    })
    record = SimpleNamespace(pk=7)
    monkeypatch.setattr(service.transaction, "atomic", nullcontext)
    monkeypatch.setattr(service.AutomaticRefreshAttempt.objects, "get", Mock(return_value=attempt))
    locked = Mock()
    locked.select_related.return_value.get.return_value = record
    monkeypatch.setattr(service.MarketplaceStoreAuthorization.objects, "select_for_update", lambda: locked)
    monkeypatch.setattr(automatic_refresh, "_attempt_key", lambda _: attempt.pk)
    monkeypatch.setattr(automatic_refresh, "require_automatic_refresh", lambda *_: None)
    monkeypatch.setattr(service, "_scope", lambda _: "bound")
    custody = Mock()
    custody.lookup_reference_by_operation.return_value = {"found": False}
    monkeypatch.setattr(service, "get_custody_backend", lambda: custody)
    provider = Mock()
    monkeypatch.setattr(marketplace_oauth_service, "resolve_oauth_provider", provider)
    with pytest.raises(ValidationError):
        service.refresh_with_commit_recovery(record, actor=SimpleNamespace(tenant_id=1), expected_token_id="old")
    custody.lookup_reference_by_operation.assert_called_once_with("automatic-refresh:attempt1", include_reference=True)
    provider.assert_not_called()


@pytest.mark.parametrize("commit_ack", ["received", "lost_but_verified", "lost_not_verified"])
def test_active_custody_receipt_recovers_local_commit_only(monkeypatch, commit_ack):
    from apps.integrations import automatic_refresh, marketplace_oauth_service
    from apps.integrations import refresh_commit_recovery as service

    actor = SimpleNamespace(tenant_id=3)
    current = SimpleNamespace(pk=9, token_id="old", credential_id="c1",
                              credential_reference_version=1, status="active", save=Mock())
    attempt = SimpleNamespace(pk="attempt1", commit_recovery={
        "schema": 1, "scope": "bound", "source_reference": service._digest("old"),
        "source_version": 1, "operation_id": "automatic-refresh:attempt1", "recover_only": True,
    })
    lookup = Mock()
    expiry = timezone.now() + timedelta(hours=2)
    lookup.lookup_reference_by_operation.return_value = {
        "found": True, "status": "active", "credential_id": "c2", "token_id": "new",
        "reference_version": 2, "expires_at": expiry.isoformat(),
    }
    monkeypatch.setattr(service, "get_custody_backend", lambda: lookup)
    provider = Mock()
    monkeypatch.setattr(marketplace_oauth_service, "resolve_oauth_provider", provider)
    monkeypatch.setattr(automatic_refresh, "_attempt_key", lambda _: attempt.pk)
    monkeypatch.setattr(automatic_refresh, "require_automatic_refresh", lambda *_: None)
    monkeypatch.setattr(service, "_scope", lambda _: "bound")
    monkeypatch.setattr(service.AutomaticRefreshAttempt.objects, "get", Mock(return_value=attempt))
    writes = Mock()
    monkeypatch.setattr(service.AutomaticRefreshAttempt.objects, "filter", Mock(return_value=writes))
    locked = Mock()
    locked.select_related.return_value.get.return_value = current
    monkeypatch.setattr(service.MarketplaceStoreAuthorization.objects, "select_for_update", lambda: locked)
    reread = Mock()
    reread.filter.return_value.first.return_value = current if commit_ack == "lost_but_verified" else None
    monkeypatch.setattr(service.MarketplaceStoreAuthorization.objects, "select_related", lambda *_: reread)
    atomic_entries = []

    @contextmanager
    def atomic():
        atomic_entries.append(None)
        yield
        if len(atomic_entries) == 2 and commit_ack != "received":
            raise DatabaseError("COMMIT acknowledgment lost")

    def rotate(row, **kwargs):
        assert (kwargs["token_id"], kwargs["credential_id"], kwargs["version"]) == ("new", "c2", 2)
        assert kwargs["expires_at"] == expiry
        assert kwargs["allow_live_references"] and kwargs["preserve_new_reference_on_failure"]
        row.token_id, row.credential_id, row.credential_reference_version = "new", "c2", 2
        return row

    monkeypatch.setattr(service.transaction, "atomic", atomic)
    rotation = Mock(side_effect=rotate)
    monkeypatch.setattr(service, "rotate_store_authorization_references", rotation)
    if commit_ack == "lost_not_verified":
        with pytest.raises(service.RefreshCommitPending):
            service.refresh_with_commit_recovery(current, actor=actor, expected_token_id="old")
    else:
        assert service.refresh_with_commit_recovery(current, actor=actor, expected_token_id="old") is current
    if commit_ack != "received":
        reread.filter.assert_called_once_with(pk=9, tenant_id=3, status="active", token_id="new",
                                             credential_id="c2", credential_reference_version=2)
    else:
        reread.filter.assert_not_called()
    first = writes.update.call_args_list[0].kwargs
    assert first["status"] == first["commit_recovery"]["phase"] == "commit_pending"
    last = writes.update.call_args.kwargs
    if commit_ack == "lost_not_verified":
        assert last["status"] == last["commit_recovery"]["phase"] == "commit_pending"
        assert last["commit_recovery"]["recover_only"] and last["next_retry_at"] is not None
    else:
        assert last["status"] == "success" and last["commit_recovery"]["phase"] == "committed"
        assert last["next_retry_at"] is None and current.last_error_code == ""
    lookup.lookup_reference_by_operation.assert_called_once_with("automatic-refresh:attempt1", include_reference=True)
    rotation.assert_called_once()
    provider.assert_not_called()
