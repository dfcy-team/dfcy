import io
import json
from datetime import datetime, timezone

import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.development.competitor_client import (
    CompetitorContractError,
    CompetitorProviderUnavailable,
    CompetitorReportClient,
    normalize_report,
)
from apps.development.models import DevelopmentRequirementCompetitorLink
from apps.development.services import create_competitor_link
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductResearch
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def report_payload(report_id="report-1", *, tenant=None, status="completed"):
    payload = {
        "report_id": report_id,
        "task_id": "task-1",
        "status": status,
        "platform": "shopee",
        "site": "PH",
        "product_id": "sku-1",
        "product_title": "Yoga jacket",
        "completed_at": "2026-07-31T15:33:36+08:00",
        "data_updated_at": "2026-07-31T15:33:36+08:00",
        "statistics": {"input": 143, "valid": 143, "positive": 18, "neutral": 9, "negative": 116},
        "summary": "Most negative feedback concerns sizing.",
        "insights": {
            "strengths": ["soft fabric"],
            "pain_points": ["runs small"],
            "recommendations": ["publish a clear size chart"],
        },
        "attributes": [
            {
                "code": "size_fit",
                "name": "Size and fit",
                "mentions": 55,
                "positive": 9,
                "neutral": 5,
                "negative": 41,
                "conclusion": "Sizing is the largest pain point.",
            }
        ],
        "cautions": ["Review sample may not represent all buyers."],
    }
    if tenant is not None:
        payload["tenant_id"] = tenant.pk
    return payload


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode()


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.payload)


def test_client_fails_closed_without_base_url():
    with pytest.raises(CompetitorProviderUnavailable):
        CompetitorReportClient(base_url="").get_report("report-1", tenant=type("Tenant", (), {"pk": 1, "code": "t"})())


def test_client_normalizes_report_and_uses_get_only():
    opener = FakeOpener({"data": report_payload()})
    tenant = type("Tenant", (), {"pk": 1, "code": "t"})()
    client = CompetitorReportClient(base_url="https://competitor.invalid/api", timeout=7, opener=opener)
    result = client.get_report("report-1", tenant=tenant)
    request, timeout = opener.requests[0]
    assert result["statistics"] == {"input": 143, "valid": 143, "positive": 18, "neutral": 9, "negative": 116}
    assert result["completed_at"].endswith("Z")
    assert request.method == "GET"
    assert request.get_header("X-tenant-id") == "1"
    assert timeout == 7


def test_client_rejects_missing_contract_fields():
    payload = report_payload()
    payload.pop("attributes")
    with pytest.raises(CompetitorContractError):
        normalize_report(payload)


def grant(user, *codes):
    role = Role.objects.create(tenant=user.tenant, name="Competitor role", code=f"competitor-{user.id}")
    role.permissions.add(*Permission.objects.filter(code__in=codes))
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)


@pytest.fixture
def requirement_context():
    tenant = Tenant.objects.create(name="Competitor tenant", code="competitor-tenant")
    user = CustomUser.objects.create_user(
        username="competitor-user",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    permission_codes = (
        "development.requirement.view",
        "development.requirement.manage",
    )
    for code in permission_codes:
        Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "development", "action": code.rsplit(".", 1)[-1]})
    grant(user, *permission_codes)
    requirement = ProductResearch.objects.create(
        tenant=tenant,
        research_no="REQ-COMP-1",
        product_name="Yoga jacket",
        created_by=user,
    )
    return tenant, user, requirement


def test_link_captures_provider_metadata_and_operator_snapshot(requirement_context):
    tenant, user, requirement = requirement_context

    class FakeClient:
        def get_report(self, report_id, *, tenant):
            return normalize_report(report_payload(report_id, tenant=tenant), tenant=tenant)

        @staticmethod
        def snapshot_payload(report):
            return {"report_id": report["report_id"], "statistics": report["statistics"], "summary": report["summary"]}

    link = create_competitor_link(
        requirement=requirement,
        actor=user,
        report_id="report-1",
        selection={
            "selected_pain_points": ["runs small"],
            "selected_strengths": ["soft fabric"],
            "selected_recommendations": ["publish a clear size chart"],
            "evidence_ids": ["e-1"],
            "operator_conclusion": "Improve sizing before sampling.",
            "excluded_items": [{"item": "shipping", "reason": "not a product defect"}],
            "reason": "High negative share",
        },
        client=FakeClient(),
    )
    assert link.external_report_id == "report-1"
    assert link.product_title == "Yoga jacket"
    assert link.decision_snapshot["report"]["statistics"]["negative"] == 116
    assert link.decision_snapshot["operator_decision"]["evidence_ids"] == ["e-1"]


def test_link_rejects_operator_text_not_present_in_provider_insights(requirement_context):
    tenant, user, requirement = requirement_context

    class FakeClient:
        def get_report(self, report_id, *, tenant):
            return normalize_report(report_payload(report_id, tenant=tenant), tenant=tenant)

        @staticmethod
        def snapshot_payload(report):
            return CompetitorReportClient.snapshot_payload(report)

    with pytest.raises(ValidationError) as raised:
        create_competitor_link(
            requirement=requirement,
            actor=user,
            report_id="report-1",
            selection={"selected_pain_points": ["invented provider pain point"]},
            client=FakeClient(),
        )
    assert "selections" in str(raised.value.detail)


def test_api_ignores_spoofed_report_metadata_and_prevents_duplicate(monkeypatch, requirement_context):
    tenant, user, requirement = requirement_context

    class FakeClient:
        def get_report(self, report_id, *, tenant):
            return normalize_report(report_payload(report_id, tenant=tenant), tenant=tenant)

        @staticmethod
        def snapshot_payload(report):
            return CompetitorReportClient.snapshot_payload(report)

    monkeypatch.setattr("apps.development.views.get_competitor_report_client", lambda: FakeClient())
    client = APIClient()
    client.force_authenticate(user=user)
    body = {
        "report_id": "report-1",
        "external_report_id": "spoofed",
        "product_title": "spoofed title",
        "selected_pain_points": ["runs small"],
    }
    first = client.post(
        f"/api/internal/development/requirements/{requirement.id}/competitors/",
        body,
        format="json",
    )
    assert first.status_code == 201
    assert first.json()["data"]["external_report_id"] == "report-1"
    assert first.json()["data"]["product_title"] == "Yoga jacket"
    duplicate = client.post(
        f"/api/internal/development/requirements/{requirement.id}/competitors/",
        body,
        format="json",
    )
    assert duplicate.status_code == 409


def test_api_delete_is_tenant_scoped_and_does_not_call_provider(monkeypatch, requirement_context):
    tenant, user, requirement = requirement_context
    link = DevelopmentRequirementCompetitorLink.objects.create(
        tenant=tenant,
        requirement=requirement,
        external_report_id="report-delete",
        task_id="task-1",
        platform="shopee",
        site="PH",
        product_id="sku-1",
        product_title="Yoga jacket",
        report_completed_at=datetime.now(timezone.utc),
        data_updated_at=datetime.now(timezone.utc),
        decision_snapshot={"schema_version": 1},
        created_by=user,
    )
    called = []
    monkeypatch.setattr("apps.development.views.get_competitor_report_client", lambda: called.append(True))
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.delete(
        f"/api/internal/development/requirements/{requirement.id}/competitors/{link.id}/"
    )
    assert response.status_code == 200
    assert not DevelopmentRequirementCompetitorLink.objects.filter(pk=link.id).exists()
    assert called == []
