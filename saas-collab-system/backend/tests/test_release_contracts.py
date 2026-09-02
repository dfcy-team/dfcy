from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.miniapp_auth import issue_miniapp_tokens
from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.releases.models import ReleaseContract, ReleaseGateResult
from apps.releases.services import (
    MINIAPP_FILING_GATE_CODE,
    REQUIRED_GATE_CODES,
    create_release_contract,
    gate_status,
    record_gate_result,
)
from apps.tenants.models import Tenant


def create_user(tenant, username):
    return CustomUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def grant(user, permission_code):
    permission = Permission.objects.get(code=permission_code)
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"{user.username}-{permission_code}",
        code=f"{user.username}-{permission_code}".replace(".", "-")[:80],
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL,
        config={"all": True},
    )


def create_payload(commit_sha="a" * 40):
    return {
        "application_code": "saas-miniapp",
        "environment": ReleaseContract.Environment.TEST,
        "commit_sha": commit_sha,
        "api_contract_version": "miniapp-v1",
        "scope": ["pages/home", "pages/releases"],
        "risk_level": ReleaseContract.RiskLevel.MEDIUM,
        "rollback_version": "0.0.9",
        "rollback_point": "artifact:stable-009",
        "stop_conditions": [
            {"metric": "login_error_rate", "operator": ">", "threshold": 0.05}
        ],
        "observation_minutes": 30,
    }


def post(client, path, data, key):
    return client.post(path, data, format="json", HTTP_IDEMPOTENCY_KEY=key)


@pytest.mark.django_db
def test_release_contract_main_flow_and_read_only_miniapp_workbench():
    tenant = Tenant.objects.create(name="Release Tenant", code="release-tenant")
    creator = create_user(tenant, "release-creator")
    business = create_user(tenant, "release-business")
    technical = create_user(tenant, "release-technical")
    security = create_user(tenant, "release-security")
    executor = create_user(tenant, "release-executor")
    viewer = create_user(tenant, "release-viewer")

    grant(creator, "release.contract.manage")
    for approver in (business, technical, security):
        grant(approver, "release.contract.approve")
    grant(executor, "release.contract.execute")
    grant(viewer, "release.contract.view")

    client = APIClient()
    client.force_authenticate(user=creator)
    created = post(
        client,
        "/api/internal/releases/contracts/",
        create_payload(),
        "release-create-001",
    )
    assert created.status_code == 201
    contract = created.json()["data"]["contract"]
    contract_id = contract["id"]
    version = contract["version"]
    assert contract["status"] == ReleaseContract.Status.DRAFT

    now = timezone.now()
    for index, gate_code in enumerate(REQUIRED_GATE_CODES, start=1):
        gate = post(
            client,
            f"/api/internal/releases/contracts/{contract_id}/gates/",
            {
                "version": version,
                "code": gate_code,
                "category": "quality",
                "status": "passed",
                "evidence_ref": f"evidence:{gate_code}",
                "evaluated_at": now,
                "expires_at": now + timedelta(days=1),
            },
            f"release-gate-{index:02d}",
        )
        assert gate.status_code == 201
        version += 1

    submitted = post(
        client,
        f"/api/internal/releases/contracts/{contract_id}/actions/submit-review/",
        {"version": version, "reason": "All required gate evidence is current."},
        "release-submit-001",
    )
    assert submitted.status_code == 200
    version = submitted.json()["data"]["contract"]["version"]
    assert submitted.json()["data"]["contract"]["status"] == ReleaseContract.Status.REVIEW_PENDING

    for approver, approval_type, key in (
        (business, "business", "release-approval-business"),
        (technical, "technical", "release-approval-technical"),
        (security, "security", "release-approval-security"),
    ):
        client.force_authenticate(user=approver)
        decision = post(
            client,
            f"/api/internal/releases/contracts/{contract_id}/approvals/",
            {
                "version": version,
                "approval_type": approval_type,
                "decision": "approved",
                "reason": f"{approval_type} review passed.",
            },
            key,
        )
        assert decision.status_code == 201
        version = decision.json()["data"]["contract"]["version"]

    assert decision.json()["data"]["contract"]["status"] == ReleaseContract.Status.APPROVED

    client.force_authenticate(user=executor)
    build = post(
        client,
        f"/api/internal/releases/contracts/{contract_id}/build/",
        {
            "version": version,
            "build_no": "build-1001",
            "commit_sha": "a" * 40,
            "artifact_hash": "b" * 64,
            "config_version": "config-v1",
            "manifest": {"lockfile": "sha256:masked"},
            "reason": "Controlled build completed.",
        },
        "release-build-001",
    )
    assert build.status_code == 201
    version = build.json()["data"]["contract"]["version"]

    actions = [
        ("upload", {}, "release-upload-001"),
        ("submit-platform-review", {}, "release-platform-submit-001"),
        (
            "record-platform-review",
            {
                "result_status": "approved",
                "scheduled_at": timezone.now() + timedelta(minutes=1),
            },
            "release-platform-result-001",
        ),
        ("start-release", {}, "release-start-001"),
        (
            "record-release-result",
            {"result_status": "released", "evidence_refs": ["platform-result:masked"]},
            "release-result-001",
        ),
        ("start-observation", {}, "release-observe-001"),
        ("complete", {}, "release-complete-001"),
    ]
    for action, extra, key in actions:
        response = post(
            client,
            f"/api/internal/releases/contracts/{contract_id}/actions/{action}/",
            {"version": version, "reason": f"Record {action}.", **extra},
            key,
        )
        assert response.status_code == 200, response.json()
        version = response.json()["data"]["contract"]["version"]

    assert response.json()["data"]["contract"]["status"] == ReleaseContract.Status.COMPLETED

    other_tenant = Tenant.objects.create(name="Other Tenant", code="other-release-tenant")
    other_creator = create_user(other_tenant, "other-release-creator")
    create_release_contract(
        actor=other_creator,
        payload=create_payload(commit_sha="d" * 40),
        idempotency_key="other-release-create-001",
    )

    client.force_authenticate(user=None)
    miniapp_access = issue_miniapp_tokens(viewer)["access_token"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {miniapp_access}")
    workbench = client.get("/api/miniapp/releases/workbench/")
    assert workbench.status_code == 200
    assert workbench.json()["data"]["read_only"] is True
    assert workbench.json()["data"]["total"] == 1
    assert workbench.json()["data"]["status_counts"]["completed"] == 1
    assert workbench.json()["data"]["recent"][0]["contract_no"].startswith("RC-")

    detail = client.get(f"/api/miniapp/releases/contracts/{contract_id}/")
    assert detail.status_code == 200
    assert detail.json()["data"]["read_only"] is True
    detail_contract = detail.json()["data"]["contract"]
    assert detail_contract["status"] == ReleaseContract.Status.COMPLETED
    serialized_detail = str(detail_contract)
    for sensitive_field in (
        "actor_id",
        "audit_events",
        "created_by_id",
        "decided_by_id",
        "recorded_by_id",
        "request_id",
    ):
        assert sensitive_field not in serialized_detail

    forbidden_write = client.post("/api/miniapp/releases/workbench/", {}, format="json")
    assert forbidden_write.status_code == 405


@pytest.mark.django_db
def test_submit_is_blocked_until_all_required_gates_pass():
    tenant = Tenant.objects.create(name="Gate Tenant", code="gate-tenant")
    creator = create_user(tenant, "gate-creator")
    grant(creator, "release.contract.manage")
    contract, _ = create_release_contract(
        actor=creator,
        payload=create_payload(),
        idempotency_key="gate-create-001",
    )
    client = APIClient()
    client.force_authenticate(user=creator)

    response = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/actions/submit-review/",
        {"version": contract.version, "reason": "Attempt without evidence."},
        "gate-submit-001",
    )

    assert response.status_code == 422
    assert response.json()["code"] == "GATE_FAILED"
    contract.refresh_from_db()
    assert contract.status == ReleaseContract.Status.DRAFT


@pytest.mark.django_db
def test_production_release_is_blocked_until_miniapp_filing_is_approved():
    tenant = Tenant.objects.create(name="Filing Gate Tenant", code="filing-gate-tenant")
    creator = create_user(tenant, "filing-gate-creator")
    grant(creator, "release.contract.manage")
    payload = create_payload()
    payload["environment"] = ReleaseContract.Environment.PRODUCTION
    contract, _ = create_release_contract(
        actor=creator,
        payload=payload,
        idempotency_key="filing-gate-create-001",
    )
    now = timezone.now()

    for index, gate_code in enumerate(REQUIRED_GATE_CODES, start=1):
        contract.refresh_from_db()
        record_gate_result(
            contract=contract,
            actor=creator,
            payload={
                "version": contract.version,
                "code": gate_code,
                "category": "quality",
                "status": ReleaseGateResult.Status.PASSED,
                "evidence_ref": f"evidence:{gate_code}",
                "evaluated_at": now,
                "expires_at": now + timedelta(days=1),
            },
            idempotency_key=f"filing-gate-base-{index:02d}",
        )

    contract.refresh_from_db()
    blocked = gate_status(contract)
    assert blocked["passed"] is False
    assert blocked["required"] == len(REQUIRED_GATE_CODES) + 1
    assert blocked["blockers"] == [
        {"code": MINIAPP_FILING_GATE_CODE, "reason": "missing"}
    ]
    client = APIClient()
    client.force_authenticate(user=creator)
    submit = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/actions/submit-review/",
        {"version": contract.version, "reason": "Attempt before filing approval."},
        "filing-gate-submit-blocked-001",
    )
    assert submit.status_code == 422
    assert submit.json()["code"] == "GATE_FAILED"

    record_gate_result(
        contract=contract,
        actor=creator,
        payload={
            "version": contract.version,
            "code": MINIAPP_FILING_GATE_CODE,
            "category": "compliance",
            "status": ReleaseGateResult.Status.PASSED,
            "evidence_ref": "filing-review:approved:masked",
            "evaluated_at": now,
            "expires_at": now + timedelta(days=30),
        },
        idempotency_key="filing-gate-approved-001",
    )

    contract.refresh_from_db()
    assert gate_status(contract)["passed"] is True


@pytest.mark.django_db
def test_creator_cannot_approve_and_one_actor_cannot_fill_multiple_roles():
    tenant = Tenant.objects.create(name="Separation Tenant", code="separation-tenant")
    creator = create_user(tenant, "separation-creator")
    approver = create_user(tenant, "separation-approver")
    grant(creator, "release.contract.approve")
    grant(approver, "release.contract.approve")
    contract, _ = create_release_contract(
        actor=creator,
        payload=create_payload(),
        idempotency_key="separation-create-001",
    )
    contract.status = ReleaseContract.Status.REVIEW_PENDING
    contract._release_service_write = True
    contract.save(update_fields=["status", "updated_at"])
    contract._release_service_write = False

    client = APIClient()
    client.force_authenticate(user=creator)
    own = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/approvals/",
        {
            "version": contract.version,
            "approval_type": "business",
            "decision": "approved",
            "reason": "Self approval attempt.",
        },
        "separation-own-001",
    )
    assert own.status_code == 422
    assert own.json()["code"] == "SEPARATION_OF_DUTIES"

    client.force_authenticate(user=approver)
    first = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/approvals/",
        {
            "version": contract.version,
            "approval_type": "business",
            "decision": "approved",
            "reason": "Business approval.",
        },
        "separation-first-001",
    )
    assert first.status_code == 201
    second = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/approvals/",
        {
            "version": first.json()["data"]["contract"]["version"],
            "approval_type": "technical",
            "decision": "approved",
            "reason": "Technical approval by same actor.",
        },
        "separation-second-001",
    )
    assert second.status_code == 422
    assert second.json()["code"] == "SEPARATION_OF_DUTIES"


@pytest.mark.django_db
def test_contract_state_cannot_be_mutated_outside_service():
    tenant = Tenant.objects.create(name="Protected Tenant", code="protected-tenant")
    creator = create_user(tenant, "protected-creator")
    contract, _ = create_release_contract(
        actor=creator,
        payload=create_payload(),
        idempotency_key="protected-create-001",
    )

    contract.status = ReleaseContract.Status.COMPLETED
    with pytest.raises(DjangoValidationError):
        contract.save()
    with pytest.raises(DjangoValidationError):
        ReleaseContract.objects.filter(pk=contract.pk).update(
            status=ReleaseContract.Status.COMPLETED
        )


@pytest.mark.django_db
def test_create_idempotency_replays_only_the_same_contract():
    tenant = Tenant.objects.create(name="Idempotent Tenant", code="idempotent-tenant")
    creator = create_user(tenant, "idempotent-creator")
    first, replayed = create_release_contract(
        actor=creator,
        payload=create_payload(),
        idempotency_key="idempotent-create-001",
    )
    second, replayed_again = create_release_contract(
        actor=creator,
        payload=create_payload(),
        idempotency_key="idempotent-create-001",
    )

    assert replayed is False
    assert replayed_again is True
    assert first.pk == second.pk

    changed = create_payload(commit_sha="c" * 40)
    with pytest.raises(Exception) as exc_info:
        create_release_contract(
            actor=creator,
            payload=changed,
            idempotency_key="idempotent-create-001",
        )
    assert getattr(exc_info.value, "error_code", "") == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_rollback_requires_independent_approval_before_execution():
    tenant = Tenant.objects.create(name="Rollback Tenant", code="rollback-tenant")
    creator = create_user(tenant, "rollback-creator")
    approver = create_user(tenant, "rollback-approver")
    executor = create_user(tenant, "rollback-executor")
    grant(approver, "release.contract.approve")
    grant(executor, "release.contract.execute")
    contract, _ = create_release_contract(
        actor=creator,
        payload=create_payload(),
        idempotency_key="rollback-create-001",
    )
    contract.status = ReleaseContract.Status.ROLLBACK_REQUIRED
    contract._release_service_write = True
    contract.save(update_fields=["status", "updated_at"])
    contract._release_service_write = False

    client = APIClient()
    client.force_authenticate(user=executor)
    blocked = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/actions/execute-rollback/",
        {"version": contract.version, "reason": "Attempt without approval."},
        "rollback-execute-blocked",
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "ROLLBACK_APPROVAL_INVALID"

    client.force_authenticate(user=approver)
    approval = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/approvals/",
        {
            "version": contract.version,
            "approval_type": "rollback",
            "decision": "approved",
            "reason": "Independent rollback approval.",
        },
        "rollback-approval-001",
    )
    assert approval.status_code == 201

    client.force_authenticate(user=executor)
    executed = post(
        client,
        f"/api/internal/releases/contracts/{contract.id}/actions/execute-rollback/",
        {
            "version": approval.json()["data"]["contract"]["version"],
            "reason": "Rollback result recorded.",
        },
        "rollback-execute-001",
    )
    assert executed.status_code == 200
    assert executed.json()["data"]["contract"]["status"] == ReleaseContract.Status.ROLLED_BACK
