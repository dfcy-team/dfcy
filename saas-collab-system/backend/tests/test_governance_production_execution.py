import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.governance.execution import OpenAIResponsesClient, run_assistant_evaluation_job
from apps.governance.models import AssistantDefinition, AssistantEvaluationJob
from apps.governance.tasks import dispatch_stale_evaluations, reconcile_stale_evaluations
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def user_for(tenant, username):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def grant(user, codes, *, scope_type=DataScope.ScopeType.ALL, config=None):
    role, _ = Role.objects.get_or_create(
        tenant=user.tenant,
        code=f"{user.username}-role",
        defaults={"name": "Evaluation role"},
    )
    permissions = [
        Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": code.split(".", 1)[0], "action": code.rsplit(".", 1)[-1]},
        )[0]
        for code in codes
    ]
    role.permissions.add(*permissions)
    UserRole.objects.get_or_create(tenant=user.tenant, user=user, role=role)
    scope, _ = DataScope.objects.get_or_create(
        tenant=user.tenant,
        role=role,
        defaults={"scope_type": scope_type, "config": config or {}},
    )
    return scope


def assistant(tenant, *, status=AssistantDefinition.Status.SANDBOX, data_class="public_demo"):
    return AssistantDefinition.objects.create(
        tenant=tenant,
        code=f"eval-{AssistantDefinition.objects.count() + 1}",
        name="Synthetic evaluator",
        description="Public demo assistant",
        status=status,
        data_class=data_class,
        allowed_tools=[],
        output_types=["risk_summary"],
        limitations=["synthetic input only"],
        human_confirmation_required=True,
        version=3,
    )


def evaluation_payload(version=3, **overrides):
    payload = {
        "scenario": "risk_summary",
        "input": "Summarize this synthetic risk example.",
        "expected_output": "A concise risk summary with no business write.",
        "version": version,
        "reason": "Production readiness evaluation",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db(transaction=True)
def test_real_evaluation_endpoint_is_async_scoped_and_idempotent(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation tenant", code="evaluation-async")
    user = user_for(tenant, "evaluation-user")
    grant(user, ["governance.assistants.view", "governance.assistants.evaluate"])
    target = assistant(tenant)
    queued = []

    def enqueue(*args, **kwargs):
        queued.append((args, kwargs))
        return SimpleNamespace(id="celery-evaluation-1")

    monkeypatch.setattr("apps.governance.views_execution.run_assistant_evaluation.apply_async", enqueue)
    client = client_for(user)
    path = f"/api/internal/governance/assistants/{target.id}/evaluations/"
    with TestCase.captureOnCommitCallbacks(execute=True):
        response = client.post(
            path,
            evaluation_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="evaluation-idempotency-1",
        )

    assert response.status_code == 202, response.json()
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["api_status"] == "blocked"
    assert data["input_length"] > 0
    job = AssistantEvaluationJob.objects.get()
    assert job.test_input == evaluation_payload()["input"]
    assert job.expected_output == evaluation_payload()["expected_output"]
    assert len(queued) == 1

    replay = client.post(
        path,
        evaluation_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="evaluation-idempotency-1",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["idempotent_replay"] is True
    assert len(queued) == 1

    conflict = client.post(
        path,
        evaluation_payload(input="a different synthetic case"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="evaluation-idempotency-1",
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_evaluation_requires_sandbox_public_demo_and_rejects_sensitive_input(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation policy tenant", code="evaluation-policy")
    user = user_for(tenant, "evaluation-policy-user")
    grant(user, ["governance.assistants.view", "governance.assistants.evaluate"])
    review_pending = assistant(tenant, status=AssistantDefinition.Status.REVIEW_PENDING)
    client = client_for(user)
    path = f"/api/internal/governance/assistants/{review_pending.id}/evaluations/"

    blocked = client.post(
        path,
        evaluation_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="evaluation-policy-1",
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "POLICY_VIOLATION"

    review_pending.status = AssistantDefinition.Status.SANDBOX
    review_pending.save(update_fields=["status"])
    sensitive = client.post(
        path,
        evaluation_payload(input="Call https://example.invalid with token=secret"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="evaluation-policy-2",
    )
    assert sensitive.status_code == 422
    assert sensitive.json()["code"] == "FIELD_VALIDATION_FAILED"
    assert not AssistantEvaluationJob.objects.exists()

    private = assistant(tenant, data_class="internal_demo")
    denied = client.post(
        f"/api/internal/governance/assistants/{private.id}/evaluations/",
        evaluation_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="evaluation-policy-3",
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "POLICY_VIOLATION"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return json.dumps(self.payload).encode("utf-8")


@pytest.mark.django_db
def test_openai_payload_is_tool_free_structured_and_completed_only(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation provider tenant", code="evaluation-provider")
    user = user_for(tenant, "evaluation-provider-user")
    target = assistant(tenant)
    job = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="A synthetic request",
        expected_output="A concise answer",
        reason="Provider contract test",
        assistant_version=target.version,
        idempotency_key_hash="a" * 64,
        request_fingerprint="b" * 64,
    )
    requests = []

    def fake_urlopen(request, **kwargs):
        requests.append((request, kwargs))
        return FakeResponse(
            {
                "id": "resp-evaluation-1",
                "status": "completed",
                "model": "gpt-test",
                "usage": {"input_tokens": 12, "output_tokens": 18, "total_tokens": 30},
                "output_text": json.dumps(
                    {
                        "assistant_output": "A concise answer",
                        "passed": True,
                        "score": 98.5,
                        "findings": [],
                        "summary": "Acceptance criterion met",
                    }
                ),
            }
        )

    monkeypatch.setattr("apps.governance.execution.urlopen", fake_urlopen)
    with override_settings(
        OPENAI_API_KEY="sk-test-only",
        OPENAI_API_KEY_FILE="",
        OPENAI_API_BASE_URL="https://api.openai.com/v1",
        OPENAI_MODEL="gpt-test",
    ):
        result = run_assistant_evaluation_job(job.id)

    job.refresh_from_db()
    assert result.status == AssistantEvaluationJob.Status.SUCCEEDED
    assert job.response_id == "resp-evaluation-1"
    assert job.assistant_output == "A concise answer"
    assert job.passed is True
    assert float(job.score) == 98.5
    body = json.loads(requests[0][0].data.decode("utf-8"))
    assert body["tools"] == []
    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["safety_identifier"].startswith("gov_")
    assert len(body["safety_identifier"]) == 64
    assert "A synthetic request" not in body["safety_identifier"]
    assert requests[0][0].get_header("Authorization") == "Bearer sk-test-only"


@pytest.mark.django_db
def test_incomplete_openai_response_is_failed_without_persisting_partial_output(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation incomplete tenant", code="evaluation-incomplete")
    user = user_for(tenant, "evaluation-incomplete-user")
    target = assistant(tenant)
    job = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="Synthetic request",
        expected_output="Expected answer",
        reason="Incomplete response test",
        assistant_version=target.version,
        idempotency_key_hash="c" * 64,
        request_fingerprint="d" * 64,
    )
    monkeypatch.setattr(
        "apps.governance.execution.urlopen",
        lambda *args, **kwargs: FakeResponse(
            {
                "id": "resp-incomplete",
                "status": "incomplete",
                "output_text": "partial sensitive provider text",
            }
        ),
    )
    with override_settings(
        OPENAI_API_KEY="sk-test-only",
        OPENAI_API_KEY_FILE="",
        OPENAI_API_BASE_URL="https://api.openai.com/v1",
        OPENAI_MODEL="gpt-test",
        OPENAI_MAX_RETRIES=0,
    ):
        run_assistant_evaluation_job(job.id)

    job.refresh_from_db()
    assert job.status == AssistantEvaluationJob.Status.FAILED
    assert job.error_code == "OPENAI_RESPONSE_INCOMPLETE"
    assert job.response_id == ""
    assert job.result == ""
    assert "partial sensitive" not in job.error_message


@pytest.mark.django_db
def test_duplicate_evaluation_delivery_claims_only_queued_once(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation duplicate tenant", code="evaluation-duplicate")
    user = user_for(tenant, "evaluation-duplicate-user")
    target = assistant(tenant)
    job = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="Synthetic request",
        expected_output="Expected answer",
        reason="Duplicate delivery test",
        assistant_version=target.version,
        idempotency_key_hash="e" * 64,
        request_fingerprint="f" * 64,
    )
    calls = []

    def evaluate(*args, **kwargs):
        calls.append(1)
        return {
            "response_id": "resp-duplicate",
            "model": "gpt-test",
            "token_usage": {"total_tokens": 2},
            "result": "Synthetic answer",
            "assistant_output": "Synthetic answer",
            "passed": True,
            "score": 100,
            "findings": [],
            "result_summary": "Passed",
        }

    monkeypatch.setattr(OpenAIResponsesClient, "evaluate", evaluate)
    first = run_assistant_evaluation_job(job.id)
    second = run_assistant_evaluation_job(job.id)
    assert first.status == AssistantEvaluationJob.Status.SUCCEEDED
    assert second.status == AssistantEvaluationJob.Status.SUCCEEDED
    assert len(calls) == 1
    assert AssistantEvaluationJob.objects.get(pk=job.id).attempts == 1


@pytest.mark.django_db
def test_evaluation_fails_closed_if_assistant_version_changes_during_provider_call(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation fence tenant", code="evaluation-fence")
    user = user_for(tenant, "evaluation-fence-user")
    target = assistant(tenant)
    job = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="Synthetic request",
        expected_output="Expected answer",
        reason="Version fence test",
        assistant_version=target.version,
        idempotency_key_hash="1" * 64,
        request_fingerprint="2" * 64,
    )

    def evaluate(*args, **kwargs):
        target.version += 1
        target.save(update_fields=["version"])
        return {
            "response_id": "resp-fence",
            "model": "gpt-test",
            "token_usage": {"total_tokens": 2},
            "result": "Synthetic answer",
            "assistant_output": "Synthetic answer",
            "passed": True,
            "score": 100,
            "findings": [],
            "result_summary": "Passed",
        }

    monkeypatch.setattr(OpenAIResponsesClient, "evaluate", evaluate)
    result = run_assistant_evaluation_job(job.id)

    assert result.status == AssistantEvaluationJob.Status.FAILED
    assert result.error_code == "ASSISTANT_VERSION_CHANGED"
    assert result.result == ""
    assert result.response_id == ""


@pytest.mark.django_db
def test_stale_provider_success_cannot_overwrite_reconciled_terminal_job(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation terminal fence tenant", code="evaluation-terminal-fence")
    user = user_for(tenant, "evaluation-terminal-fence-user")
    target = assistant(tenant)
    job = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="Synthetic request",
        expected_output="Expected answer",
        reason="Terminal fence test",
        assistant_version=target.version,
        idempotency_key_hash="7" * 64,
        request_fingerprint="8" * 64,
    )

    def evaluate(*args, **kwargs):
        # Model the stale reconciler winning the row lock while provider I/O
        # is in flight. The worker must observe this terminal state later.
        job.status = AssistantEvaluationJob.Status.FAILED
        job.error_code = "EVALUATION_WORKER_LOST"
        job.error_message = "Evaluation worker did not finish within the service deadline."
        job.finished_at = timezone.now()
        job._execution_service_write = True
        try:
            job.save(update_fields=["status", "error_code", "error_message", "finished_at"])
        finally:
            job._execution_service_write = False
        return {
            "response_id": "resp-stale-success",
            "model": "gpt-test",
            "token_usage": {"total_tokens": 2},
            "result": "Synthetic answer",
            "assistant_output": "Synthetic answer",
            "passed": True,
            "score": 100,
            "findings": [],
            "result_summary": "Passed",
        }

    monkeypatch.setattr(OpenAIResponsesClient, "evaluate", evaluate)
    result = run_assistant_evaluation_job(job.id)

    assert result.status == AssistantEvaluationJob.Status.FAILED
    assert result.error_code == "EVALUATION_WORKER_LOST"
    assert result.response_id == ""


@pytest.mark.django_db
def test_governance_compensators_republish_stale_queue_and_close_lost_worker(monkeypatch):
    tenant = Tenant.objects.create(name="Evaluation compensation tenant", code="evaluation-compensation")
    user = user_for(tenant, "evaluation-compensation-user")
    target = assistant(tenant)
    queued = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="Synthetic request",
        expected_output="Expected answer",
        reason="Compensation queue test",
        assistant_version=target.version,
        idempotency_key_hash="3" * 64,
        request_fingerprint="4" * 64,
    )
    queued.created_at = timezone.now() - timedelta(minutes=10)
    queued._execution_service_write = True
    queued.save(update_fields=["created_at"])
    queued._execution_service_write = False
    monkeypatch.setattr(
        "apps.governance.tasks.run_assistant_evaluation.apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-compensation-1"),
    )
    assert dispatch_stale_evaluations() == {"dispatched": 1}
    queued.refresh_from_db()
    assert queued.celery_task_id == "celery-compensation-1"

    lost = AssistantEvaluationJob.objects.create(
        tenant=tenant,
        assistant=target,
        requested_by=user,
        scenario="risk_summary",
        demo_input_ref="synthetic-input",
        test_input="Synthetic request",
        expected_output="Expected answer",
        reason="Compensation worker test",
        assistant_version=target.version,
        idempotency_key_hash="5" * 64,
        request_fingerprint="6" * 64,
        status=AssistantEvaluationJob.Status.RUNNING,
        attempts=1,
        started_at=timezone.now() - timedelta(hours=1),
    )
    assert reconcile_stale_evaluations() == {"reconciled": 1}
    lost.refresh_from_db()
    assert lost.status == AssistantEvaluationJob.Status.FAILED
    assert lost.error_code == "EVALUATION_WORKER_LOST"
