import pytest
from django.core.exceptions import ValidationError

from apps.supply_chain import inbound_cancellation
from apps.supply_chain.models import BusinessEvent, InboundOrder, InternalStockReceipt, domain_write
from tests.test_supply_chain_v2_logistics import setup, create, arrive, generate, client
from tests.test_supply_chain_v2_foundation import internal_user, world


def draft_inbound(world):
    buyer, shipment, _, carrier, warehouse = setup(world)
    api = client(buyer)
    batch, _ = create(api, [shipment], carrier, key="cancel-batch")
    batch = arrive(api, batch)
    inbound = generate(api, batch, warehouse)
    return buyer, InboundOrder.objects.get(pk=inbound["id"])


@pytest.mark.django_db
def test_cancel_draft_inbound_is_audited_and_keeps_lines(world):
    buyer, inbound = draft_inbound(world)
    line_ids = list(inbound.lines.values_list("pk", flat=True))
    result = inbound_cancellation.cancel_inbound(buyer, inbound.pk,
        {"expected_version": inbound.version, "reason": "duplicate draft"}, "cancel-inbound")
    assert result.status == InboundOrder.Status.CANCELLED
    assert result.version == inbound.version + 1
    assert list(result.lines.values_list("pk", flat=True)) == line_ids
    assert not InternalStockReceipt.objects.filter(inbound=result).exists()
    event = BusinessEvent.objects.get(aggregate_type="inboundorder", aggregate_id=result.pk,
                                      action="inbound_cancelled")
    assert event.payload["reason"] == "duplicate draft"


@pytest.mark.django_db
def test_cancel_inbound_checks_reason_version_permission_and_replay(world):
    buyer, inbound = draft_inbound(world)
    with pytest.raises(ValidationError):
        inbound_cancellation.cancel_inbound(buyer, inbound.pk,
            {"expected_version": inbound.version, "reason": "  "}, "empty-reason")
    with pytest.raises(ValidationError):
        inbound_cancellation.cancel_inbound(buyer, inbound.pk,
            {"expected_version": inbound.version + 1, "reason": "because"}, "stale")
    denied = internal_user(world, "cancel-denied", scope="own")
    with pytest.raises(Exception):
        inbound_cancellation.cancel_inbound(denied, inbound.pk,
            {"expected_version": inbound.version, "reason": "because"}, "denied")
    payload = {"expected_version": inbound.version, "reason": "duplicate"}
    inbound_cancellation.cancel_inbound(buyer, inbound.pk, payload, "replayed")
    replay = inbound_cancellation.cancel_inbound(buyer, inbound.pk, payload, "replayed")
    assert replay.status == InboundOrder.Status.CANCELLED
    assert BusinessEvent.objects.filter(aggregate_id=inbound.pk, action="inbound_cancelled").count() == 1


@pytest.mark.django_db
def test_confirmed_inbound_cannot_be_cancelled(world):
    buyer, inbound = draft_inbound(world)
    with domain_write():
        inbound.status = InboundOrder.Status.CONFIRMED
        inbound.stock_receipt_ref = "receipt"
        inbound.save()
    with pytest.raises(ValidationError):
        inbound_cancellation.cancel_inbound(buyer, inbound.pk,
            {"expected_version": inbound.version, "reason": "undo"}, "confirmed")


@pytest.mark.django_db
def test_cancel_api_is_readable_and_blocks_new_financial_actions(world):
    from apps.supply_chain import costs
    buyer,inbound=draft_inbound(world)
    api=client(buyer)
    response=api.post(f'/api/internal/supply-chain/v2/inbound-orders/{inbound.pk}/cancel/',{'expected_version':inbound.version,'reason':'用户要求作废'},format='json',HTTP_IDEMPOTENCY_KEY='cancel-api')
    assert response.status_code==200,response.data
    assert response.data['data']['status']=='cancelled'
    with pytest.raises(ValidationError):costs.target_for(buyer,'inbound',inbound.pk)
    detail=api.get(f'/api/internal/supply-chain/v2/inbound-orders/{inbound.pk}/')
    assert detail.status_code==200 and detail.data['data']['status']=='cancelled'
