from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.pilot.models import (
    EntryDecision,
    PerformanceRun,
    PilotAuditEvent,
    PilotEnvironment,
    PilotEvidenceReference,
    PilotTargetAlias,
    RecoveryPlan,
    ReleasePlan,
    SecurityReview,
    VerificationRun,
)
from apps.tenants.models import Tenant


def user_for(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def grant(user, codes, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"{user.username}-ui-p8-{Role.objects.filter(tenant=user.tenant).count() + 1}", name="UI P8 role")
    role.permissions.add(*Permission.objects.filter(code__in=codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    return DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def environment():
    return PilotEnvironment.objects.get_or_create(code="pilot", defaults={"name": "Controlled pilot"})[0]


def register_controls(tenant, env, references=(), aliases=()):
    for reference in references:
        PilotEvidenceReference.objects.get_or_create(tenant=tenant, environment=env, reference=reference)
    for alias in aliases:
        PilotTargetAlias.objects.get_or_create(tenant=tenant, environment=env, alias=alias)


def controlled_create(model, **kwargs):
    instance = model(**kwargs)
    instance._pilot_state_service_write = True
    instance.save(force_insert=True)
    instance._pilot_state_service_write = False
    return instance


def register_default_controls(tenant, env):
    register_controls(
        tenant,
        env,
        references=(
            "demo-security-evidence", "demo-verification-plan", "demo-performance-plan",
            "demo-result", "demo-expired", "demo", "demo-verification-result",
            "demo-performance-result",
        ),
        aliases=("demo-app",),
    )


def security_payload(**overrides):
    payload = {
        "review_type": "network_boundary",
        "environment": "pilot",
        "scope_summary": "Masked controlled network review",
        "risk_level": "medium",
        "finance_scope": None,
        "evidence_refs": ["demo-security-evidence"],
        "expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
    }
    payload.update(overrides)
    return payload


def verification_payload(**overrides):
    payload = {
        "category": "browser_e2e",
        "environment": "pilot",
        "target_alias": "demo-app",
        "data_class": "synthetic",
        "planned_start_at": (timezone.now() + timedelta(days=1)).isoformat(),
        "planned_end_at": (timezone.now() + timedelta(days=2)).isoformat(),
        "success_criteria": ["Demo login flow renders"],
        "evidence_refs": ["demo-verification-plan"],
    }
    payload.update(overrides)
    return payload


UI_P8_PATHS = (
    "/api/internal/pilot/control-room/?environment=pilot",
    "/api/internal/pilot/security-reviews/",
    "/api/internal/pilot/verification-runs/",
    "/api/internal/pilot/performance-runs/",
    "/api/internal/pilot/entry-decisions/",
)


@pytest.mark.parametrize("path", UI_P8_PATHS)
@pytest.mark.django_db
def test_ui_p8_collections_require_authentication(path):
    response = APIClient().get(path)
    assert (response.status_code, response.json()["code"]) == (401, "AUTH_REQUIRED")


@pytest.mark.django_db
def test_security_review_creation_is_scoped_idempotent_and_owner_is_server_only():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-security")
    user = user_for(tenant, "security-planner")
    env = environment()
    register_default_controls(tenant, env)
    grant(user, ["pilot.security_review.view", "pilot.security_review.plan"], DataScope.ScopeType.CUSTOM, {"pilot_environments": ["pilot"]})
    client = client_for(user)
    payload = security_payload()

    created = client.post("/api/internal/pilot/security-reviews/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-security-create")
    replay = client.post("/api/internal/pilot/security-reviews/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-security-create")
    forbidden = client.post("/api/internal/pilot/security-reviews/", security_payload(owner_id=999), format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-security-owner")

    assert created.status_code == 201, created.json()
    assert replay.status_code == 200
    assert created.json()["data"]["owner_id"] == user.id
    assert set(created.json()["data"]) == {
        "id", "code", "review_type", "environment", "scope_summary", "risk_level", "owner_id",
        "finance_scope", "evidence_refs", "expires_at", "status", "creator_id", "reviewer_id",
        "reviewed_at", "review_reason", "version", "audit_ref", "created_at", "updated_at",
        "idempotent_replay",
    }
    assert (forbidden.status_code, forbidden.json()["code"]) == (422, "FORBIDDEN_FIELD")
    assert SecurityReview.objects.count() == 1


@pytest.mark.django_db
def test_idempotency_conflict_list_summary_and_filter_validation():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-contract")
    user = user_for(tenant, "contract-planner")
    env = environment()
    register_default_controls(tenant, env)
    grant(user, ["pilot.security_review.view", "pilot.security_review.plan"])
    client = client_for(user)
    created = client.post("/api/internal/pilot/security-reviews/", security_payload(), format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-contract-create")
    conflict = client.post("/api/internal/pilot/security-reviews/", security_payload(scope_summary="Different request"), format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-contract-create")
    listed = client.get("/api/internal/pilot/security-reviews/")
    invalid_filter = client.get("/api/internal/pilot/security-reviews/?status=not-real")

    assert created.status_code == 201
    assert (conflict.status_code, conflict.json()["code"]) == (409, "IDEMPOTENCY_CONFLICT")
    assert listed.status_code == 200
    assert "evidence_refs" not in listed.json()["data"]["results"][0]
    assert (invalid_filter.status_code, invalid_filter.json()["code"]) == (400, "REQUEST_INVALID")


@pytest.mark.django_db
def test_sensitive_free_text_and_target_environment_scope_are_rejected_without_write():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-patch-scope")
    user = user_for(tenant, "patch-planner")
    env = environment()
    register_default_controls(tenant, env)
    PilotEnvironment.objects.create(code="sandbox", name="Sandbox")
    scope = grant(user, ["pilot.security_review.view", "pilot.security_review.plan"], DataScope.ScopeType.CUSTOM, {"pilot_environments": ["pilot"]})
    client = client_for(user)
    sensitive = client.post("/api/internal/pilot/security-reviews/", security_payload(scope_summary="token=not-allowed"), format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-sensitive-create")
    created = client.post("/api/internal/pilot/security-reviews/", security_payload(), format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-patch-create")
    review_id = created.json()["data"]["id"]
    scope.config = {"pilot_environments": ["pilot"], "security_review_ids": [review_id]}
    scope.save(update_fields=["config"])
    denied = client.patch(f"/api/internal/pilot/security-reviews/{review_id}/", {"version": 1, "environment": "sandbox"}, format="json")

    assert (sensitive.status_code, sensitive.json()["code"]) == (422, "VALIDATION_ERROR")
    assert denied.status_code == 403
    assert SecurityReview.objects.get(pk=review_id).environment.code == "pilot"


@pytest.mark.django_db
def test_performance_thresholds_are_json_safe_and_no_load_test_is_executed():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-performance")
    user = user_for(tenant, "performance-planner")
    env = environment()
    register_default_controls(tenant, env)
    grant(user, ["pilot.performance.view", "pilot.performance.plan"])
    response = client_for(user).post("/api/internal/pilot/performance-runs/", {
        "scenario": "Synthetic read-only dashboard workload", "environment": "pilot", "workload_profile": "synthetic",
        "max_rps": 20, "concurrency": 5, "duration_seconds": 60,
        "thresholds": {"p95_ms_max": 800, "error_rate_max": 0.01, "cpu_percent_max": 80, "memory_percent_max": 80},
        "evidence_refs": ["demo-performance-plan"],
    }, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-performance-create")

    assert response.status_code == 201, response.json()
    assert PerformanceRun.objects.get().thresholds["p95_ms_max"] == 800.0


@pytest.mark.django_db
def test_unknown_or_unregistered_scope_is_denied():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-bad-scope")
    user = user_for(tenant, "bad-scope")
    env = environment()
    register_default_controls(tenant, env)
    grant(user, ["pilot.security_review.view"], DataScope.ScopeType.CUSTOM, {"environment_ids": ["pilot"]})

    response = client_for(user).get("/api/internal/pilot/security-reviews/")

    assert (response.status_code, response.json()["code"]) == (403, "DATA_SCOPE_INVALID")


@pytest.mark.django_db
def test_finance_boundary_requires_finance_permission_and_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-finance")
    planner = user_for(tenant, "finance-boundary-planner")
    env = environment()
    register_default_controls(tenant, env)
    grant(planner, ["pilot.security_review.plan"])
    payload = security_payload(review_type="finance_boundary", finance_scope={"platforms": ["demo-platform"], "currencies": ["USD"]})

    denied = client_for(planner).post("/api/internal/pilot/security-reviews/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-finance-denied")
    grant(planner, ["finance.view"], DataScope.ScopeType.CUSTOM, {"platforms": ["demo-platform"], "currencies": ["USD"]})
    allowed = client_for(planner).post("/api/internal/pilot/security-reviews/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-finance-allowed")

    assert denied.status_code == 403
    assert allowed.status_code == 201, allowed.json()


@pytest.mark.django_db
def test_verification_state_machine_enforces_separation_and_result_contract():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-verification")
    creator = user_for(tenant, "verification-creator")
    reviewer = user_for(tenant, "verification-reviewer")
    recorder = user_for(tenant, "verification-recorder")
    env = environment()
    register_default_controls(tenant, env)
    grant(creator, ["pilot.verification.view", "pilot.verification.plan"])
    grant(reviewer, ["pilot.verification.view", "pilot.verification.review"])
    grant(recorder, ["pilot.verification.view", "pilot.verification.record"])
    created = client_for(creator).post("/api/internal/pilot/verification-runs/", verification_payload(), format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-verification-create")
    run_id = created.json()["data"]["id"]
    submitted = client_for(creator).post(f"/api/internal/pilot/verification-runs/{run_id}/submit/", {"version": 1, "reason": "Submit demo evidence"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-verification-submit")
    self_review = client_for(creator).post(f"/api/internal/pilot/verification-runs/{run_id}/approve/", {"version": 2, "review_reason": "Self review forbidden"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-verification-self-review")
    approved = client_for(reviewer).post(f"/api/internal/pilot/verification-runs/{run_id}/approve/", {"version": 2, "review_reason": "Independent review"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-verification-approve")
    reviewer_record = client_for(reviewer).post(f"/api/internal/pilot/verification-runs/{run_id}/record-result/", {
        "version": 3, "reason": "Forbidden reviewer result", "result": "passed", "result_summary": "Demo",
        "evidence_refs": ["demo-result"], "started_at": (timezone.now() - timedelta(minutes=5)).isoformat(),
        "finished_at": timezone.now().isoformat(), "error_code": None, "error_message": None,
    }, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-verification-reviewer-result")
    recorded = client_for(recorder).post(f"/api/internal/pilot/verification-runs/{run_id}/record-result/", {
        "version": 3, "reason": "Record external synthetic result", "result": "passed", "result_summary": "Demo passed",
        "evidence_refs": ["demo-result"], "started_at": (timezone.now() - timedelta(minutes=5)).isoformat(),
        "finished_at": timezone.now().isoformat(), "error_code": None, "error_message": None,
    }, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-verification-result")

    assert created.status_code == 201
    assert submitted.status_code == 200
    assert self_review.status_code in {403, 409}
    assert approved.status_code == 200, approved.json()
    assert reviewer_record.status_code in {403, 409}
    assert recorded.status_code == 200, recorded.json()
    assert recorded.json()["data"]["status"] == "passed"


@pytest.mark.django_db
def test_expired_draft_is_lazily_expired_and_cannot_be_submitted():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-expiry")
    user = user_for(tenant, "expiry-planner")
    env = environment()
    grant(user, ["pilot.security_review.view", "pilot.security_review.plan"])
    register_default_controls(tenant, env)
    review = controlled_create(SecurityReview,
        tenant=tenant, environment=env, code="SEC-EXPIRED", review_type="network_boundary",
        scope_summary="Expired demo", risk_level="medium", finance_scope=None,
        evidence_refs=["demo-expired"], expires_at=timezone.now() - timedelta(seconds=1),
        creator=user, owner=user, idempotency_key_hash="e" * 64,
    )
    response = client_for(user).post(f"/api/internal/pilot/security-reviews/{review.id}/submit/", {"version": 1, "reason": "Too late"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p8-expired-submit")

    review.refresh_from_db()
    assert response.status_code == 409
    assert review.status == "expired"
    assert PilotAuditEvent.objects.filter(object_type="security_review", object_id=str(review.id), action="expire", actor_type="system").exists()


@pytest.mark.django_db
def test_state_and_audit_records_cannot_be_mutated_or_deleted_directly():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-protected")
    user = user_for(tenant, "protected-user")
    env = environment()
    register_default_controls(tenant, env)
    with pytest.raises(DjangoValidationError):
        VerificationRun.objects.create(
            tenant=tenant, environment=env, code="VER-BYPASS", category="browser_e2e", target_alias="demo-app",
            data_class="synthetic", planned_start_at=timezone.now(), planned_end_at=timezone.now() + timedelta(hours=1),
            success_criteria=["demo"], evidence_refs=["demo"], creator=user, owner=user, idempotency_key_hash="b" * 64,
        )
    run = controlled_create(VerificationRun,
        tenant=tenant, environment=env, code="VER-PROTECTED", category="browser_e2e", target_alias="demo-app",
        data_class="synthetic", planned_start_at=timezone.now(), planned_end_at=timezone.now() + timedelta(hours=1),
        success_criteria=["demo"], evidence_refs=["demo"], creator=user, owner=user, idempotency_key_hash="p" * 64,
    )
    run.status = "approved"
    with pytest.raises(DjangoValidationError):
        run.save()
    with pytest.raises(DjangoValidationError):
        VerificationRun.objects.filter(pk=run.pk).update(status="approved")
    with pytest.raises(DjangoValidationError):
        VerificationRun.objects.filter(pk=run.pk).delete()


@pytest.mark.django_db
def test_control_room_stays_pending_and_never_claims_deployment():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-control")
    user = user_for(tenant, "control-viewer")
    environment()
    grant(user, ["pilot.control.view"])

    response = client_for(user).get("/api/internal/pilot/control-room/?environment=pilot")

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["capability_status"] == "pending"
    assert response.json()["data"]["readiness_status"] == "blocked"
    assert "deployment" not in response.json()["data"]


@pytest.mark.django_db
def test_finance_patch_requires_explicit_scope_and_revalidates_target_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-finance-patch")
    user = user_for(tenant, "finance-patch-planner")
    env = environment()
    register_default_controls(tenant, env)
    grant(user, ["pilot.security_review.view", "pilot.security_review.plan"])
    grant(user, ["finance.view"], DataScope.ScopeType.CUSTOM, {"platforms": ["demo-platform"], "currencies": ["USD"]})
    client = client_for(user)
    finance = client.post(
        "/api/internal/pilot/security-reviews/",
        security_payload(review_type="finance_boundary", finance_scope={"platforms": ["demo-platform"], "currencies": ["USD"]}),
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-finance-patch-create",
    )
    review_id = finance.json()["data"]["id"]

    implicit_clear = client.patch(
        f"/api/internal/pilot/security-reviews/{review_id}/",
        {"version": 1, "review_type": "network_boundary"},
        format="json",
    )
    explicit_clear = client.patch(
        f"/api/internal/pilot/security-reviews/{review_id}/",
        {"version": 1, "review_type": "network_boundary", "finance_scope": None},
        format="json",
    )
    missing_scope = client.patch(
        f"/api/internal/pilot/security-reviews/{review_id}/",
        {"version": 2, "review_type": "finance_boundary"},
        format="json",
    )
    restored = client.patch(
        f"/api/internal/pilot/security-reviews/{review_id}/",
        {"version": 2, "review_type": "finance_boundary", "finance_scope": {"platforms": ["demo-platform"], "currencies": ["USD"]}},
        format="json",
    )

    assert (implicit_clear.status_code, implicit_clear.json()["code"]) == (422, "VALIDATION_ERROR")
    assert explicit_clear.status_code == 200, explicit_clear.json()
    assert (missing_scope.status_code, missing_scope.json()["code"]) == (422, "VALIDATION_ERROR")
    assert restored.status_code == 200, restored.json()
    assert PilotAuditEvent.objects.filter(object_type="security_review", action="patch", outcome="failed", error_code="VALIDATION_ERROR").count() >= 2


@pytest.mark.django_db
def test_verification_target_and_evidence_must_be_registered_controls():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-controlled-refs")
    user = user_for(tenant, "controlled-ref-planner")
    env = environment()
    grant(user, ["pilot.verification.view", "pilot.verification.plan"])
    client = client_for(user)

    denied = client.post(
        "/api/internal/pilot/verification-runs/",
        verification_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-unregistered-target",
    )
    register_controls(tenant, env, references=("demo-verification-plan",), aliases=("demo-app",))
    allowed = client.post(
        "/api/internal/pilot/verification-runs/",
        verification_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-registered-target",
    )

    assert (denied.status_code, denied.json()["code"]) == (422, "VALIDATION_ERROR")
    assert allowed.status_code == 201, allowed.json()
    assert PilotAuditEvent.objects.filter(object_type="verification", action="create", outcome="failed").exists()


def entry_sources(tenant, env, user):
    security = controlled_create(
        SecurityReview,
        tenant=tenant, environment=env, code="SEC-ENTRY", review_type="network_boundary",
        scope_summary="Controlled entry evidence", risk_level="medium", finance_scope=None,
        evidence_refs=["demo-security-evidence"], expires_at=timezone.now() + timedelta(days=7), status="approved",
        creator=user, owner=user, reviewer=user, reviewed_at=timezone.now(), idempotency_key_hash="1" * 64,
    )
    verification = controlled_create(
        VerificationRun,
        tenant=tenant, environment=env, code="VER-ENTRY", category="browser_e2e", target_alias="demo-app",
        data_class="synthetic", planned_start_at=timezone.now(), planned_end_at=timezone.now() + timedelta(hours=1),
        success_criteria=["demo"], evidence_refs=["demo-verification-result"], status="passed",
        creator=user, owner=user, reviewer=user, recorder=user, idempotency_key_hash="2" * 64,
    )
    performance = controlled_create(
        PerformanceRun,
        tenant=tenant, environment=env, code="PERF-ENTRY", scenario="Synthetic entry evidence", workload_profile="synthetic",
        max_rps=10, concurrency=2, duration_seconds=30,
        thresholds={"p95_ms_max": 800, "error_rate_max": 0.01, "cpu_percent_max": 80, "memory_percent_max": 80},
        evidence_refs=["demo-performance-result"], status="passed", creator=user, owner=user, reviewer=user,
        recorder=user, idempotency_key_hash="3" * 64,
    )
    recovery = RecoveryPlan.objects.create(
        tenant=tenant, environment=env, name="Demo recovery evidence", rpo_minutes=60, rto_minutes=120,
        backup_summary="Masked demo backup", backup_checksum_masked="masked-checksum", status="approved",
        created_by=user, approved_by=user, idempotency_key_hash="4" * 64, reason="Controlled demo evidence",
    )
    release = ReleasePlan.objects.create(
        tenant=tenant, environment=env, release_channel="controlled_pilot", commit_sha="a" * 40,
        demo_tenant_refs=["demo-tenant"], observation_minutes=30, stop_conditions=["demo-stop"],
        rollback_point="demo-rollback", database_compatibility="compatible", status="approved",
        created_by=user, approved_by=user, idempotency_key_hash="5" * 64, reason="Controlled demo evidence",
    )
    return security, verification, performance, recovery, release


@pytest.mark.django_db
def test_entry_approval_revalidates_the_frozen_evidence_snapshot():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-entry-revalidate")
    creator = user_for(tenant, "entry-creator")
    reviewer = user_for(tenant, "entry-reviewer")
    env = environment()
    register_default_controls(tenant, env)
    view_codes = [
        "pilot.entry.view", "pilot.security_review.view", "pilot.verification.view",
        "pilot.performance.view", "pilot.recovery.view", "pilot.release.view",
    ]
    grant(creator, [*view_codes, "pilot.entry.plan"])
    grant(reviewer, [*view_codes, "pilot.entry.review"])
    security, verification, performance, recovery, release = entry_sources(tenant, env, creator)
    created = client_for(creator).post(
        "/api/internal/pilot/entry-decisions/",
        {
            "environment": "pilot", "decision": "go", "scope_summary": "Controlled entry decision",
            "security_review_ids": [security.id], "verification_run_ids": [verification.id],
            "performance_run_ids": [performance.id], "recovery_plan_ids": [recovery.id],
            "release_plan_ids": [release.id], "expires_at": (timezone.now() + timedelta(days=7)).isoformat(),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-entry-create",
    )
    decision_id = created.json()["data"]["id"]
    submitted = client_for(creator).post(
        f"/api/internal/pilot/entry-decisions/{decision_id}/submit/",
        {"version": 1, "reason": "Freeze controlled evidence"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-entry-submit",
    )
    security.expires_at = timezone.now() - timedelta(seconds=1)
    security._pilot_state_service_write = True
    security.save(update_fields=["expires_at", "updated_at"])
    security._pilot_state_service_write = False
    approved = client_for(reviewer).post(
        f"/api/internal/pilot/entry-decisions/{decision_id}/approve/",
        {"version": 2, "review_reason": "Revalidate before approval"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-entry-approve-stale",
    )

    assert created.status_code == 201, created.json()
    assert submitted.status_code == 200, submitted.json()
    assert (approved.status_code, approved.json()["code"]) == (409, "STATE_CONFLICT")
    assert EntryDecision.objects.get(pk=decision_id).status == "submitted"
    assert PilotAuditEvent.objects.filter(object_type="entry", object_id=str(decision_id), action="approve", outcome="failed").exists()


@pytest.mark.django_db
def test_ui_p8_failure_audit_covers_scope_and_version_failures():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p8-failure-audit")
    user = user_for(tenant, "failure-audit-user")
    env = environment()
    register_default_controls(tenant, env)
    scope = grant(user, ["pilot.security_review.view", "pilot.security_review.plan"])
    client = client_for(user)
    created = client.post(
        "/api/internal/pilot/security-reviews/",
        security_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p8-failure-create",
    )
    review_id = created.json()["data"]["id"]
    conflict = client.patch(
        f"/api/internal/pilot/security-reviews/{review_id}/",
        {"version": 99, "scope_summary": "Stale update"},
        format="json",
    )
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {"pilot_environments": ["sandbox"]}
    scope.save(update_fields=["scope_type", "config"])
    forbidden = client.get("/api/internal/pilot/security-reviews/")

    assert conflict.status_code == 409
    assert forbidden.status_code == 403
    assert PilotAuditEvent.objects.filter(
        object_type="security_review",
        action="patch",
        outcome="failed",
        error_code=conflict.json()["code"],
    ).exists()
    assert PilotAuditEvent.objects.filter(
        object_type="security_review",
        action="read",
        outcome="failed",
        error_code=forbidden.json()["code"],
    ).exists()
