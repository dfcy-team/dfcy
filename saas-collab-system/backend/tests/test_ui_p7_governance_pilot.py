from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.governance.models import ApiContract, AssistantDefinition
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.pilot.models import CapacityObservation, PilotAuditEvent, PilotEnvironment, ReadinessGate, RecoveryPlan, ReleasePlan, TopologyService
from apps.purchasing.models import PurchaseOrder
from apps.rpa.models import RPATask
from apps.tenants.models import Tenant


def user_for(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def grant(user, codes, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"{user.username}-ui-p7", name="UI P7 role")
    role.permissions.add(*Permission.objects.filter(code__in=codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def environment(code="controlled-pilot"):
    return PilotEnvironment.objects.create(code=code, name=code)


UI_P7_ENDPOINTS = [
    ("get", "/api/internal/governance/api-contracts/"),
    ("get", "/api/internal/governance/api-contracts/999/"),
    ("post", "/api/internal/governance/api-contracts/check-mock/"),
    ("get", "/api/internal/governance/assistants/"),
    ("get", "/api/internal/governance/assistants/999/"),
    ("post", "/api/internal/governance/assistants/999/evaluate-mock/"),
    ("get", "/api/internal/pilot/readiness/"),
    ("get", "/api/internal/pilot/topology/"),
    ("post", "/api/internal/pilot/topology/verify-mock/"),
    ("get", "/api/internal/pilot/capacity/summary/"),
    ("get", "/api/internal/pilot/capacity/observations/"),
    ("get", "/api/internal/pilot/recovery-plans/"),
    ("post", "/api/internal/pilot/recovery-plans/"),
    ("get", "/api/internal/pilot/recovery-plans/999/"),
    *[("post", f"/api/internal/pilot/recovery-plans/999/{action}/") for action in ("submit-review", "approve", "reject", "schedule", "start", "resume", "cancel")],
    ("get", "/api/internal/pilot/recovery-drills/"),
    ("post", "/api/internal/pilot/recovery-drills/999/record-result/"),
    ("get", "/api/internal/pilot/release-plans/"),
    ("post", "/api/internal/pilot/release-plans/"),
    ("get", "/api/internal/pilot/release-plans/999/"),
    *[("post", f"/api/internal/pilot/release-plans/999/{action}/") for action in (
        "submit-review", "approve", "reject", "schedule", "start", "resume", "cancel",
        "record-result", "approve-rollback", "resume-rollback", "record-rollback",
    )],
]


@pytest.mark.parametrize(("method", "path"), UI_P7_ENDPOINTS)
@pytest.mark.django_db
def test_every_ui_p7_endpoint_requires_authentication(method, path):
    response = getattr(APIClient(), method)(path, {}, format="json")
    assert response.status_code == 401, (method, path, response.content)
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.django_db
def test_ui_p7_routes_require_authentication_and_declared_permission():
    anonymous = APIClient().get("/api/internal/pilot/readiness/")
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-auth")
    user = user_for(tenant, "no-pilot-permission")
    denied = client_for(user).get("/api/internal/pilot/readiness/")

    assert anonymous.status_code == 401
    assert denied.status_code == 403
    assert denied.json()["success"] is False


@pytest.mark.django_db
def test_readiness_applies_environment_and_gate_custom_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-readiness")
    user = user_for(tenant, "readiness-viewer")
    env = environment()
    ReadinessGate.objects.create(environment=env, code="ci", name="CI", status="passed", expires_at=timezone.now() + timedelta(days=1))
    ReadinessGate.objects.create(environment=env, code="security", name="Security", status="failed", expires_at=timezone.now() + timedelta(days=1))
    grant(user, ["pilot.readiness.view"], DataScope.ScopeType.CUSTOM, {"environment_ids": [env.code], "gate_codes": ["ci"]})

    response = client_for(user).get("/api/internal/pilot/readiness/")

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["overall_status"] == "passed"
    assert [gate["gate_code"] for gate in response.json()["data"]["gates"]] == ["ci"]
    assert set(response.json()["data"]["gates"][0]) == {
        "gate_code", "name", "status", "evidence_at", "expires_at", "blockers", "owner", "evidence_refs",
    }


@pytest.mark.django_db
def test_topology_mock_is_scoped_and_has_no_business_side_effects():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-topology")
    user = user_for(tenant, "topology-checker")
    env = environment()
    TopologyService.objects.create(environment=env, service_name="backend", host_role="application", network_zone="controlled_app", exposure="private", host_ref_masked="app-***")
    grant(user, ["pilot.topology.view", "pilot.topology.verify"], DataScope.ScopeType.CUSTOM, {
        "environment_ids": [env.code], "service_names": ["backend"], "network_zones": ["controlled_app"],
    })
    before = (PurchaseOrder.objects.count(), RPATask.objects.count())

    response = client_for(user).post(
        "/api/internal/pilot/topology/verify-mock/",
        {"environment_id": env.code, "services": [{"service_name": "backend", "host_role": "application", "network_zone": "controlled_app", "exposure": "app_host_only"}], "reason": "fixed demo only"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p7-topology-0001",
    )

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["api_status"] == "mock"
    assert (PurchaseOrder.objects.count(), RPATask.objects.count()) == before


@pytest.mark.django_db
def test_capacity_status_and_threshold_contract_preserves_critical_semantics():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-capacity")
    user = user_for(tenant, "capacity-viewer")
    env = environment()
    grant(user, ["pilot.capacity.view"])
    now = timezone.now()
    observations = [
        (CapacityObservation.Status.NORMAL, 55, 70, 90, 70),
        (CapacityObservation.Status.WARNING, 75, 70, 90, 70),
        (CapacityObservation.Status.CRITICAL, 95, 70, 90, 90),
        (CapacityObservation.Status.UNKNOWN, None, 70, 90, None),
        (CapacityObservation.Status.STALE, 50, 70, 90, None),
    ]
    for index, (capacity_status, value, warning, critical, _expected) in enumerate(observations):
        CapacityObservation.objects.create(
            environment=env,
            service_name=f"backend-{index}",
            metric_code="cpu_percent",
            value=value,
            unit="percent",
            warning_threshold=warning,
            critical_threshold=critical,
            status=capacity_status,
            observed_at=now,
        )

    client = client_for(user)
    for capacity_status, _value, _warning, _critical, expected_threshold in observations:
        response = client.get(f"/api/internal/pilot/capacity/observations/?status={capacity_status}")
        assert response.status_code == 200, response.json()
        results = response.json()["data"]["results"]
        assert len(results) == 1
        assert results[0]["status"] == capacity_status
        assert results[0]["threshold"] == expected_threshold


@pytest.mark.django_db
def test_governance_fixed_checks_do_not_call_tools_or_write_business_data():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-governance")
    user = user_for(tenant, "governance-checker")
    grant(user, ["governance.api.view", "governance.api.check", "governance.assistants.view", "governance.assistants.evaluate"])
    contract = ApiContract.objects.create(module="pilot", name="Readiness", method="GET", path="/api/internal/pilot/readiness/", owner="architecture", version="ui-p7-v1", permission_code="pilot.readiness.view", data_scope_keys=["environment_ids"], status="sandbox")
    assistant = AssistantDefinition.objects.create(code="readiness-assistant", name="Readiness assistant", description="Demo", status="mock", data_class="internal_demo", allowed_tools=[], output_types=["risk_summary"], limitations=["No tools"], human_confirmation_required=True, version=1)
    before = (PurchaseOrder.objects.count(), RPATask.objects.count())
    client = client_for(user)

    checked = client.post("/api/internal/governance/api-contracts/check-mock/", {"contract_ids": [contract.id], "sample_case": "success"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-contract-0001")
    evaluated = client.post(f"/api/internal/governance/assistants/{assistant.id}/evaluate-mock/", {"scenario": "catalog_review", "demo_input_ref": "demo-governance", "version": 1, "reason": "fixed demo"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-assistant-0001")

    assert checked.status_code == 200, checked.json()
    assert evaluated.status_code == 200, evaluated.json()
    assert evaluated.json()["data"]["tool_calls"] == []
    assert evaluated.json()["data"]["business_writes"] == []
    assert (PurchaseOrder.objects.count(), RPATask.objects.count()) == before


@pytest.mark.django_db
def test_recovery_plan_creation_is_idempotent_audited_and_state_protected():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-recovery")
    user = user_for(tenant, "recovery-planner")
    env = environment()
    grant(user, ["pilot.recovery.view", "pilot.recovery.plan"])
    payload = {"environment_id": env.code, "name": "Demo recovery", "rpo_minutes": 30, "rto_minutes": 60, "backup_summary": "Masked demo", "backup_checksum_masked": "sha256:demo-***", "reason": "planning only"}
    client = client_for(user)

    first = client.post("/api/internal/pilot/recovery-plans/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-recovery-create-0001")
    replay = client.post("/api/internal/pilot/recovery-plans/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-recovery-create-0001")
    conflict = client.post("/api/internal/pilot/recovery-plans/", {**payload, "name": "Different"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-recovery-create-0001")
    plan = RecoveryPlan.objects.get()

    assert first.status_code == 201
    assert replay.status_code == 200
    assert conflict.status_code == 409
    assert PilotAuditEvent.objects.filter(recovery_plan=plan, action="create").count() == 1
    plan.status = RecoveryPlan.Status.APPROVED
    with pytest.raises(DjangoValidationError):
        plan.save()
    with pytest.raises(DjangoValidationError):
        RecoveryPlan.objects.filter(pk=plan.pk).update(status=RecoveryPlan.Status.APPROVED)


@pytest.mark.django_db
def test_release_review_separation_and_gate_are_enforced():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-release")
    creator = user_for(tenant, "release-creator")
    reviewer = user_for(tenant, "release-reviewer")
    env = environment()
    for code in ("code", "ci", "security"):
        ReadinessGate.objects.create(environment=env, code=code, name=code, status="passed", expires_at=timezone.now() + timedelta(days=1))
    grant(creator, ["pilot.release.view", "pilot.release.plan", "pilot.release.review"])
    grant(reviewer, ["pilot.release.view", "pilot.release.review"])
    payload = {"environment_id": env.code, "release_channel": "demo", "commit_sha": "1" * 40, "tag": "demo", "demo_tenant_refs": ["demo-tenant"], "observation_minutes": 30, "stop_conditions": ["demo stop"], "rollback_point": "demo point", "database_compatibility": "verified", "reason": "planning only"}
    created = client_for(creator).post("/api/internal/pilot/release-plans/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-release-create-0001")
    plan_id = created.json()["data"]["id"]
    submitted = client_for(creator).post(f"/api/internal/pilot/release-plans/{plan_id}/submit-review/", {"version": 1, "reason": "submit", "approval_ref": "demo-approval"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-release-submit-0001")
    self_review = client_for(creator).post(f"/api/internal/pilot/release-plans/{plan_id}/approve/", {"version": 2, "reason": "approve", "approval_ref": "demo-approval"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-release-review-0001")
    approved = client_for(reviewer).post(f"/api/internal/pilot/release-plans/{plan_id}/approve/", {"version": 2, "reason": "approve", "approval_ref": "demo-approval"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-release-review-0002")

    assert created.status_code == 201
    assert submitted.status_code == 200
    assert self_review.status_code == 422
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == ReleasePlan.Status.APPROVED
    failed_event = PilotAuditEvent.objects.get(outcome=PilotAuditEvent.Outcome.FAILED)
    assert failed_event.error_code == "SEPARATION_OF_DUTIES"
    assert failed_event.from_status == failed_event.to_status == ReleasePlan.Status.REVIEW_PENDING


@pytest.mark.django_db
def test_pilot_audit_events_cannot_be_updated_or_deleted():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-audit")
    user = user_for(tenant, "audit-user")
    event = PilotAuditEvent.objects.create(tenant=tenant, actor=user, object_type="demo", object_id="1", action="demo", permission_code="pilot.readiness.view", reason="demo", idempotency_key_hash="a" * 64, version=1)

    event.reason = "changed"
    with pytest.raises(DjangoValidationError):
        event.save()
    with pytest.raises(DjangoValidationError):
        PilotAuditEvent.objects.filter(pk=event.pk).delete()


@pytest.mark.django_db
def test_unknown_ui_p7_scope_key_is_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-invalid-scope")
    user = user_for(tenant, "invalid-scope")
    environment()
    grant(user, ["pilot.readiness.view"], DataScope.ScopeType.CUSTOM, {"environment_ids": ["controlled-pilot"], "unknown": ["value"]})

    response = client_for(user).get("/api/internal/pilot/readiness/")

    assert response.status_code == 403
    assert response.json()["code"] == "DATA_SCOPE_INVALID"


@pytest.mark.django_db
def test_ui_p7_errors_use_exact_envelope_and_status_codes():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-errors")
    user = user_for(tenant, "error-contract")
    environment()
    grant(user, ["pilot.readiness.view", "pilot.recovery.view", "pilot.recovery.plan"])
    client = client_for(user)

    unknown = client.get("/api/internal/pilot/readiness/?unexpected=1")
    invalid_page = client.get("/api/internal/pilot/recovery-plans/?page_size=101")
    invalid_body = client.post(
        "/api/internal/pilot/recovery-plans/",
        {"environment_id": "controlled-pilot", "unexpected": "value"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p7-errors-create-0001",
    )

    assert (unknown.status_code, unknown.json()["code"], unknown.json()["data"]) == (400, "UNKNOWN_FIELD", None)
    assert (invalid_page.status_code, invalid_page.json()["code"], invalid_page.json()["data"]) == (400, "INVALID_PAGINATION", None)
    assert (invalid_body.status_code, invalid_body.json()["code"], invalid_body.json()["data"]) == (400, "UNKNOWN_FIELD", None)


@pytest.mark.django_db
def test_contract_check_body_outside_scope_is_403_and_duplicate_ids_are_422():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-contract-scope")
    user = user_for(tenant, "contract-scope")
    allowed = ApiContract.objects.create(module="pilot", name="Allowed", method="GET", path="/allowed/", owner="architecture", version="v1", permission_code="pilot.readiness.view", data_scope_keys=["environment_ids"], status="sandbox")
    blocked = ApiContract.objects.create(module="pilot", name="Blocked", method="GET", path="/blocked/", owner="architecture", version="v1", permission_code="pilot.readiness.view", data_scope_keys=["environment_ids"], status="sandbox")
    grant(user, ["governance.api.check"], DataScope.ScopeType.CUSTOM, {"api_contract_ids": [allowed.id]})
    client = client_for(user)

    outside = client.post("/api/internal/governance/api-contracts/check-mock/", {"contract_ids": [blocked.id], "sample_case": "success"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-contract-scope-0001")
    duplicate = client.post("/api/internal/governance/api-contracts/check-mock/", {"contract_ids": [allowed.id, allowed.id], "sample_case": "success"}, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-contract-scope-0002")

    assert (outside.status_code, outside.json()["code"]) == (403, "DATA_SCOPE_FORBIDDEN")
    assert (duplicate.status_code, duplicate.json()["code"]) == (422, "FIELD_VALIDATION_FAILED")


@pytest.mark.django_db
def test_all_scope_excludes_uncontrolled_environments_and_external_rpa_users():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-controlled-only")
    internal = user_for(tenant, "controlled-internal")
    external = user_for(tenant, "controlled-external", CustomUser.UserType.EXTERNAL)
    rpa = user_for(tenant, "controlled-rpa", CustomUser.UserType.RPA)
    controlled = environment()
    uncontrolled = environment("uncontrolled-pilot")
    uncontrolled.status = "disabled"
    uncontrolled.save(update_fields=["status"])
    for env in (controlled, uncontrolled):
        ReadinessGate.objects.create(environment=env, code="ci", name="CI", status="passed", expires_at=timezone.now() + timedelta(days=1))
    for user in (internal, external, rpa):
        grant(user, ["pilot.readiness.view"])

    assert client_for(internal).get("/api/internal/pilot/readiness/?environment_id=controlled-pilot").status_code == 200
    assert client_for(internal).get("/api/internal/pilot/readiness/?environment_id=uncontrolled-pilot").status_code == 403
    assert client_for(external).get("/api/internal/pilot/readiness/").status_code == 403
    assert client_for(rpa).get("/api/internal/pilot/readiness/").status_code == 403


@pytest.mark.django_db
def test_release_critical_fields_cannot_bypass_transition_service():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-release-protection")
    user = user_for(tenant, "release-protection")
    env = environment()
    plan = ReleasePlan.objects.create(
        tenant=tenant, environment=env, release_channel="demo", commit_sha="1" * 40, tag="demo",
        demo_tenant_refs=["demo-tenant"], observation_minutes=30, stop_conditions=["demo stop"],
        rollback_point="demo point", database_compatibility="verified", created_by=user,
        idempotency_key_hash="b" * 64, reason="planning only",
    )

    plan.commit_sha = "2" * 40
    with pytest.raises(DjangoValidationError):
        plan.save()
    with pytest.raises(DjangoValidationError):
        ReleasePlan.objects.filter(pk=plan.pk).update(rollback_point="changed")


@pytest.mark.django_db
def test_workflow_bulk_create_is_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-bulk-protection")
    user = user_for(tenant, "bulk-protection")
    env = environment()
    recovery = RecoveryPlan(
        tenant=tenant, environment=env, name="Bulk recovery", rpo_minutes=30, rto_minutes=60,
        backup_summary="Masked", backup_checksum_masked="sha256:demo", created_by=user,
        idempotency_key_hash="e" * 64, reason="must use controlled creation",
    )
    release = ReleasePlan(
        tenant=tenant, environment=env, release_channel="demo", commit_sha="1" * 40,
        demo_tenant_refs=["demo-tenant"], observation_minutes=30, stop_conditions=["demo stop"],
        rollback_point="demo point", database_compatibility="verified", created_by=user,
        idempotency_key_hash="f" * 64, reason="must use controlled creation",
    )

    with pytest.raises(DjangoValidationError):
        RecoveryPlan.objects.bulk_create([recovery])
    with pytest.raises(DjangoValidationError):
        ReleasePlan.objects.bulk_create([release])
    assert RecoveryPlan.objects.count() == 0
    assert ReleasePlan.objects.count() == 0


@pytest.mark.django_db
def test_plan_creation_failures_are_immutably_audited():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-create-failure-audit")
    user = user_for(tenant, "create-failure-audit")
    env = environment()
    grant(user, ["pilot.recovery.plan", "pilot.release.plan"])
    client = client_for(user)

    recovery = client.post(
        "/api/internal/pilot/recovery-plans/",
        {"environment_id": env.code, "unexpected": "blocked"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p7-recovery-create-failed-0001",
    )
    release = client.post(
        "/api/internal/pilot/release-plans/",
        {
            "environment_id": env.code, "release_channel": "demo", "commit_sha": "not-a-sha",
            "tag": "demo", "demo_tenant_refs": ["demo-tenant"], "observation_minutes": 30,
            "stop_conditions": ["demo stop"], "rollback_point": "demo point",
            "database_compatibility": "verified", "reason": "invalid controlled plan",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p7-release-create-failed-0001",
    )
    missing_key = client.post(
        "/api/internal/pilot/recovery-plans/",
        {"environment_id": env.code},
        format="json",
    )

    assert (recovery.status_code, recovery.json()["code"]) == (400, "UNKNOWN_FIELD")
    assert (release.status_code, release.json()["code"]) == (422, "FIELD_VALIDATION_FAILED")
    assert (missing_key.status_code, missing_key.json()["code"]) == (422, "FIELD_VALIDATION_FAILED")
    events = list(PilotAuditEvent.objects.filter(outcome=PilotAuditEvent.Outcome.FAILED).order_by("object_type"))
    assert len(events) == 3
    assert {event.object_type for event in events} == {"recovery_plan", "release_plan"}
    assert {event.error_code for event in events} == {"UNKNOWN_FIELD", "FIELD_VALIDATION_FAILED"}
    assert all(event.object_id.startswith("uncreated:") and event.from_status == event.to_status == "" for event in events)
    with pytest.raises(DjangoValidationError):
        PilotAuditEvent.objects.filter(pk=events[0].pk).delete()


@pytest.mark.django_db
def test_plan_id_only_scope_cannot_create_a_new_recovery_plan():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-create-scope")
    owner = user_for(tenant, "existing-owner")
    scoped_user = user_for(tenant, "id-only-planner")
    env = environment()
    existing = RecoveryPlan.objects.create(
        tenant=tenant, environment=env, name="Existing", rpo_minutes=30, rto_minutes=60,
        backup_summary="Masked", backup_checksum_masked="sha256:demo", created_by=owner,
        idempotency_key_hash="c" * 64, reason="fixture",
    )
    grant(scoped_user, ["pilot.recovery.plan"], DataScope.ScopeType.CUSTOM, {"recovery_plan_ids": [existing.id]})

    response = client_for(scoped_user).post(
        "/api/internal/pilot/recovery-plans/",
        {"environment_id": env.code, "name": "Blocked", "rpo_minutes": 30, "rto_minutes": 60, "backup_summary": "Masked", "backup_checksum_masked": "sha256:demo", "reason": "must remain blocked"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p7-id-only-create-0001",
    )

    assert (response.status_code, response.json()["code"]) == (403, "DATA_SCOPE_FORBIDDEN")
    assert RecoveryPlan.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
def test_expired_rollback_is_rejected_and_written_to_immutable_failure_audit():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-rollback-expired")
    creator = user_for(tenant, "rollback-creator")
    recorder = user_for(tenant, "rollback-recorder")
    env = environment()
    grant(recorder, ["pilot.release.rollback"])
    plan = ReleasePlan.objects.create(
        tenant=tenant, environment=env, release_channel="demo", commit_sha="1" * 40, tag="demo",
        demo_tenant_refs=["demo-tenant"], observation_minutes=30, stop_conditions=["demo stop"],
        rollback_point="demo point", database_compatibility="verified", created_by=creator,
        idempotency_key_hash="d" * 64, reason="fixture", status=ReleasePlan.Status.ROLLBACK_REQUIRED,
        rollback_approval_ref="demo-expired-ref", rollback_approved_by=creator,
        rollback_approved_at=timezone.now() - timedelta(hours=2),
        rollback_approval_expires_at=timezone.now() - timedelta(hours=1),
    )

    response = client_for(recorder).post(
        f"/api/internal/pilot/release-plans/{plan.id}/record-rollback/",
        {"version": 1, "reason": "record expired rollback", "rollback_approval_ref": "demo-expired-ref", "rollback_status": "rolled_back", "result_summary": "demo result", "evidence_refs": ["demo-evidence"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="ui-p7-expired-rollback-0001",
    )

    assert (response.status_code, response.json()["code"]) == (422, "ROLLBACK_APPROVAL_EXPIRED")
    event = PilotAuditEvent.objects.get(release_plan=plan, outcome=PilotAuditEvent.Outcome.FAILED)
    assert event.error_code == "ROLLBACK_APPROVAL_EXPIRED"
    assert event.from_status == event.to_status == ReleasePlan.Status.ROLLBACK_REQUIRED
    with pytest.raises(DjangoValidationError):
        event.delete()


@pytest.mark.django_db
def test_rollback_approval_reference_is_unique_across_plans():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-rollback-unique")
    creator = user_for(tenant, "unique-creator")
    approver = user_for(tenant, "unique-approver")
    env = environment()
    grant(approver, ["pilot.release.rollback"])
    plans = [
        ReleasePlan.objects.create(
            tenant=tenant, environment=env, release_channel="demo", commit_sha=str(index) * 40, tag=f"demo-{index}",
            demo_tenant_refs=["demo-tenant"], observation_minutes=30, stop_conditions=["demo stop"],
            rollback_point="demo point", database_compatibility="verified", created_by=creator,
            idempotency_key_hash=str(index) * 64, reason="fixture", status=ReleasePlan.Status.ROLLBACK_REQUIRED,
        )
        for index in (1, 2)
    ]
    client = client_for(approver)
    payload = {"version": 1, "reason": "approve rollback", "rollback_approval_ref": "demo-unique-ref", "approval_expires_at": (timezone.now() + timedelta(hours=1)).isoformat()}

    first = client.post(f"/api/internal/pilot/release-plans/{plans[0].id}/approve-rollback/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-rollback-unique-0001")
    second = client.post(f"/api/internal/pilot/release-plans/{plans[1].id}/approve-rollback/", payload, format="json", HTTP_IDEMPOTENCY_KEY="ui-p7-rollback-unique-0002")

    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (422, "POLICY_VIOLATION")


@pytest.mark.django_db
def test_rollback_approval_reference_has_database_uniqueness():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p7-rollback-db-unique")
    creator = user_for(tenant, "rollback-db-creator")
    env = environment()
    common = {
        "tenant": tenant,
        "environment": env,
        "release_channel": "demo",
        "demo_tenant_refs": ["demo-tenant"],
        "observation_minutes": 30,
        "stop_conditions": ["demo stop"],
        "rollback_point": "demo point",
        "database_compatibility": "verified",
        "created_by": creator,
        "reason": "fixture",
        "status": ReleasePlan.Status.ROLLBACK_REQUIRED,
        "rollback_approval_ref": "demo-database-unique-ref",
    }
    ReleasePlan.objects.create(commit_sha="1" * 40, idempotency_key_hash="1" * 64, **common)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ReleasePlan.objects.create(commit_sha="2" * 40, idempotency_key_hash="2" * 64, **common)
