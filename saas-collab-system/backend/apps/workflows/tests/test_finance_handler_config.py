import pytest

from apps.workflows.models import PaymentApprovalFlow
from tests.test_supply_payment_request_evidence import _grant, _setup_request
from tests.test_supply_chain_v2_foundation import world


@pytest.mark.django_db
def test_payment_flow_finance_handler_optional_and_immutable_when_published(world, monkeypatch):
    buyer, api, _shipment, _account, _row, reviewer, _reviewer_api = _setup_request(world, monkeypatch)
    _grant(buyer, "workflow.approvals.manage", "supply.v2.view", "supply.v2.manage")
    body = {
        "flow_key": "finance-handler-config", "payment_kind": "shipment", "nature": "corporate",
        "minimum_amount": "0", "reviewer_id": reviewer.pk, "finance_handler_id": buyer.pk,
        "publish": True,
    }
    created = api.post("/api/internal/workflow/payment-flows/", body, format="json")
    assert created.status_code == 201, created.data
    flow = PaymentApprovalFlow.objects.get(pk=created.data["data"]["id"])
    assert flow.finance_handler_id == buyer.pk

    listing = api.get("/api/internal/workflow/payment-flows/")
    item = next(row for row in listing.data["data"] if row["id"] == flow.pk)
    assert item["finance_handler_id"] == buyer.pk
    assert item["finance_handler_name"]

    flow.finance_handler = reviewer
    with pytest.raises(Exception, match="immutable"):
        flow.save()


@pytest.mark.django_db
def test_payment_flow_accepts_legacy_unconfigured_finance_handler(world, monkeypatch):
    buyer, api, _shipment, _account, _row, reviewer, _reviewer_api = _setup_request(world, monkeypatch)
    _grant(buyer, "workflow.approvals.manage")
    result = api.post("/api/internal/workflow/payment-flows/", {
        "flow_key": "legacy-no-handler", "payment_kind": "shipment", "nature": "corporate",
        "minimum_amount": "0", "reviewer_id": reviewer.pk, "publish": False,
    }, format="json")
    assert result.status_code == 201, result.data
    flow = PaymentApprovalFlow.objects.get(pk=result.data["data"]["id"])
    assert flow.finance_handler_id is None
