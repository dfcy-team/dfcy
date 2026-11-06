from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from . import services
from .api import key, validated
from .models import BusinessEvent, SettlementRecord
from .models import PurchaseOrder
from .permissions import VIEW, internal_orders
from .shipment_sources import accessible_shipments
from .views import InternalAPI

SEED_ACTION = "count_difference_case_seeded"
CHOICE_ACTION = "count_difference_choice_saved"
AGGREGATE = "suppliershipment"
OPTIONS = ("supplement_supplier", "supplier_waived", "return_goods", "pending_review", "wrong_item_net_settlement")


class ChoiceInput(serializers.Serializer):
    source_purchase_id = serializers.IntegerField(min_value=1)
    source_shipment_id = serializers.IntegerField(min_value=1)
    option = serializers.ChoiceField(choices=OPTIONS)
    notes = serializers.CharField(max_length=2000, allow_blank=True, default="")
    net_difference_amount = serializers.DecimalField(max_digits=14, decimal_places=4, required=False)
    expected_event_id = serializers.IntegerField(min_value=1)


def _seed_events(actor):
    return BusinessEvent.objects.filter(
        tenant_id=actor.tenant_id,
        aggregate_type=AGGREGATE,
        action=SEED_ACTION,
    )


def _latest_selection(actor, purchase_id, shipment_id):
    return BusinessEvent.objects.filter(
        tenant_id=actor.tenant_id,
        aggregate_type=AGGREGATE,
        aggregate_id=shipment_id,
        action=CHOICE_ACTION,
        payload__source_purchase_id=purchase_id,
        payload__source_shipment_id=shipment_id,
    ).order_by("-id").first()


class CountDifferenceChoices(InternalAPI):
    def get(self, request):
        # Reads follow the same view-level order/source scoping as shipment pages.
        orders = internal_orders(request.user, PurchaseOrder.objects.all(), VIEW)
        accessible = accessible_shipments(orders).filter(tenant_id=request.user.tenant_id)
        accessible_ids = set(accessible.values_list("pk", flat=True))
        seeds = list(_seed_events(request.user).order_by("aggregate_id", "id"))
        rows = []
        for seed in seeds:
            if seed.aggregate_id not in accessible_ids:
                continue
            payload = seed.payload
            current = _latest_selection(
                request.user, payload["source_purchase_id"], payload["source_shipment_id"])
            selected = current.payload if current else {}
            settlement = SettlementRecord.objects.filter(shipment_id=seed.aggregate_id).select_related("current_revision").first()
            historical_paid = bool(
                settlement and settlement.current_revision_id
                and settlement.current_revision.notes.startswith("HIST-PH-COUNT-20261106")
            )
            rows.append({
                **payload,
                "option": "historical_paid" if historical_paid else selected.get("option", "pending_review"),
                "historical_paid": historical_paid,
                "net_difference_amount": selected.get("net_difference_amount"),
                "notes": selected.get("notes", ""),
                "event_id": current.pk if current else seed.pk,
                "updated_at": current.created_at if current else seed.created_at,
            })
        return Response({"data": rows})

    @transaction.atomic
    def post(self, request):
        services._internal(request.user)
        services._tenant_lock(request.user)
        data = validated(ChoiceInput, request)
        if data["option"] == "wrong_item_net_settlement" and ("net_difference_amount" not in data or not data["notes"].strip()):
            raise ValidationError("错发换款需填写净差金额（正数我方应补，负数我方应收/抵，0为无净差）和换款依据。")
        seed = _seed_events(request.user).filter(
            aggregate_id=data["source_shipment_id"],
            payload__source_purchase_id=data["source_purchase_id"],
            payload__source_shipment_id=data["source_shipment_id"],
        ).first()
        if seed is None:
            raise NotFound("清点差额记录不可访问。")
        shipment = services._internal_shipments(request.user).filter(pk=seed.aggregate_id).first()
        if shipment is None:
            raise NotFound("发货单不可访问。")
        settlement = SettlementRecord.objects.filter(shipment=shipment).select_related("current_revision").first()
        if settlement and settlement.current_revision_id and settlement.current_revision.notes.startswith("HIST-PH-COUNT-20261106"):
            raise ValidationError("该差额已按历史已付款处理，只读显示。")
        body = {
            "source_purchase_id": data["source_purchase_id"],
            "source_shipment_id": data["source_shipment_id"],
            "source_purchase": seed.payload["source_purchase"],
            "source_shipment": seed.payload["source_shipment"],
            "option": data["option"],
            "notes": data["notes"],
            "net_difference_amount": str(data["net_difference_amount"]) if data["option"] == "wrong_item_net_settlement" else None,
            "selection_only": True,
        }
        request_key = key(request)
        replay = services._prior_event(request.user, shipment, CHOICE_ACTION, request_key, body)
        if replay:
            return Response({"data": {**body, "event_id": replay.pk}})
        prior = _latest_selection(request.user, data["source_purchase_id"], data["source_shipment_id"])
        current_version = prior.pk if prior else seed.pk
        if data["expected_event_id"] != current_version:
            raise ValidationError("清点差额记录已更新，请刷新后重试。")
        with services.domain_write():
            services._event(request.user, shipment, CHOICE_ACTION, request_key, body,
                audit={"option": data["option"], "selection_only": True})
        result = {**body, "event_id": _latest_selection(request.user, data["source_purchase_id"], data["source_shipment_id"]).pk}
        return Response({"data": result}, status=201)
