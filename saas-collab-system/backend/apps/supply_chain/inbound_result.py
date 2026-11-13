"""Read-only inbound results opened from notification links."""
from django.core import signing
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.accounts.models import CustomUser
from .models import InboundOrder
from .views import ReadAPI

SALT = "supply-chain.inbound-result.v1"


def result_path(inbound):
    token = signing.Signer(salt=SALT).sign_object([inbound.tenant_id, inbound.pk])
    return f"/inbound-result/{token}"


class InboundResult(ReadAPI):
    def get(self, request, token):
        user = request.user
        try:
            tenant_id, inbound_id = signing.Signer(salt=SALT).unsign_object(token)
        except (signing.BadSignature, ValueError, TypeError):
            raise NotFound("入库结果链接无效。")
        if not user.is_active or user.user_type != CustomUser.UserType.INTERNAL or user.tenant_id != tenant_id:
            raise NotFound("入库结果不可查看。")
        inbound = InboundOrder.objects.filter(
            tenant_id=tenant_id, pk=inbound_id, status="confirmed"
        ).select_related("batch", "warehouse").first()
        if inbound is None:
            raise NotFound("入库结果不可查看。")
        rows = [
            {"sku": line.shipment_line.sku_code_snapshot, "name": line.shipment_line.product_name_snapshot,
             "expected": line.expected_quantity, "received": line.received_quantity, "extra": False}
            for line in inbound.lines.select_related("shipment_line").order_by("pk")
        ]
        rows.extend(
            {"sku": line.sku_code_snapshot, "name": line.product_name_snapshot,
             "expected": 0, "received": line.received_quantity, "extra": True}
            for line in inbound.extra_lines.filter(is_active=True).order_by("pk")
        )
        response = Response({"data": {
            "number": inbound.number, "batch_number": inbound.batch.number,
            "country": inbound.batch.country_code_snapshot, "warehouse": inbound.warehouse.name,
            "confirmed_at": inbound.confirmed_at, "lines": rows,
        }})
        response["Cache-Control"] = "private, no-store"
        return response
