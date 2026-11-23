"""Regression coverage for the live finance initialization publication guards."""
import gzip
import hashlib

import pytest
from rest_framework.exceptions import ValidationError

from apps.finance import summary_initialization
from apps.finance.summary_models import (
    FinanceSummaryCalculation,
    FinanceSummaryDataset,
    FinanceSummaryState,
)
from apps.finance.summary_service import READ_PERMISSIONS
from tests.test_sales_management import create_scope, grant, user_for


@pytest.fixture
def actor_scope():
    tenant, _, store, _ = create_scope("finance-preserve-live")
    user = user_for(tenant, "finance-preserve-live")
    for code in (*READ_PERMISSIONS, "finance.import"):
        grant(user, code)
    return user, store


@pytest.mark.django_db
def test_status_exposes_job_dates_and_scope_but_not_raw_request(actor_scope):
    user, store = actor_scope
    dataset = FinanceSummaryDataset.objects.create(
        tenant=user.tenant, label="seed", source_hash="a" * 64,
        document_file="seed.gz", created_by=user, active=False,
    )
    job = FinanceSummaryCalculation.objects.create(
        tenant=user.tenant, dataset=dataset, actor=user, cache_key="b" * 64,
        kind="rebuild", revision=0,
        request={"bootstrap": True, "scope": {"stores": [store.pk]}, "private": "secret"},
        status="ready",
    )
    payload = summary_initialization.initialization_status(user)["initialization_job"]
    assert payload["id"] == job.pk
    assert payload["scope"] == {"stores": [store.pk]}
    assert "created_at" in payload and "finished_at" in payload
    assert "request" not in payload and "private" not in payload


@pytest.mark.parametrize(
    "evidence", ["attribution_false", "attribution_missing", "coverage_false", "coverage_missing"]
)
@pytest.mark.django_db
def test_publish_rejects_incomplete_evidence_without_writes(actor_scope, tmp_path, monkeypatch, evidence):
    user, store = actor_scope
    metadata = {
        "bootstrap_candidate": True,
        "database_scope": {"stores": [store.pk]},
        "checkpoint": {},
        "reconciliation": {"conservation_passed": True, "attribution_complete": True},
        "source_checks": {"coverage_complete": True},
    }
    if evidence == "attribution_false":
        metadata["reconciliation"]["attribution_complete"] = False
    elif evidence == "attribution_missing":
        del metadata["reconciliation"]["attribution_complete"]
    elif evidence == "coverage_false":
        metadata["source_checks"]["coverage_complete"] = False
    else:
        del metadata["source_checks"]

    content = b"synthetic candidate only"
    path = tmp_path / "candidate.html.gz"
    path.write_bytes(gzip.compress(content))
    candidate = FinanceSummaryDataset.objects.create(
        tenant=user.tenant, label="synthetic", source_hash=hashlib.sha256(content).hexdigest(),
        document_file=path.name, created_by=user, active=False, metadata=metadata,
    )
    monkeypatch.setattr("apps.finance.summary_service.private_root", lambda: tmp_path)
    monkeypatch.setattr(summary_initialization, "source_checkpoint", lambda ids: {})
    monkeypatch.setattr("apps.finance.summary_jobs.current_dataset", lambda job: candidate)
    state = FinanceSummaryState.objects.create(dataset=candidate, updated_by=user)
    state_updated_at = state.updated_at
    FinanceSummaryCalculation.objects.create(
        tenant=user.tenant, dataset=candidate, actor=user,
        cache_key=hashlib.sha256(evidence.encode()).hexdigest(), kind="rebuild", revision=0,
        request={"bootstrap": True}, status="ready", result_dataset=candidate,
    )

    with pytest.raises(ValidationError):
        summary_initialization.publish_candidate(user, candidate.pk)

    candidate.refresh_from_db()
    state.refresh_from_db()
    from apps.finance.models import FinanceAuditLog

    assert candidate.active is False
    assert state.updated_at == state_updated_at
    assert not FinanceAuditLog.objects.filter(action="summary_initialize_publish").exists()


@pytest.mark.django_db
def test_complete_synthetic_candidate_publishes_idempotently(actor_scope, tmp_path, monkeypatch):
    user, store = actor_scope
    content = b"synthetic candidate only"
    (tmp_path / "candidate.html.gz").write_bytes(gzip.compress(content))
    candidate = FinanceSummaryDataset.objects.create(
        tenant=user.tenant, label="synthetic", source_hash=hashlib.sha256(content).hexdigest(),
        document_file="candidate.html.gz", created_by=user, active=False,
        metadata={
            "bootstrap_candidate": True,
            "database_scope": {"stores": [store.pk]},
            "checkpoint": {},
            "reconciliation": {"conservation_passed": True, "attribution_complete": True},
            "source_checks": {"coverage_complete": True},
        },
    )
    FinanceSummaryState.objects.create(dataset=candidate, updated_by=user)
    FinanceSummaryCalculation.objects.create(
        tenant=user.tenant, dataset=candidate, actor=user, cache_key="c" * 64,
        kind="rebuild", revision=0, request={"bootstrap": True}, status="ready",
        result_dataset=candidate,
    )
    monkeypatch.setattr("apps.finance.summary_service.private_root", lambda: tmp_path)
    monkeypatch.setattr(summary_initialization, "source_checkpoint", lambda ids: {})
    monkeypatch.setattr("apps.finance.summary_jobs.current_dataset", lambda job: candidate)

    assert summary_initialization.publish_candidate(user, candidate.pk).pk == candidate.pk
    assert summary_initialization.publish_candidate(user, candidate.pk).pk == candidate.pk
    candidate.refresh_from_db()
    from apps.finance.models import FinanceAuditLog

    assert candidate.active is True
    assert FinanceAuditLog.objects.filter(
        action="summary_initialize_publish", object_id=str(candidate.pk)
    ).count() == 1
