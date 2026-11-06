"""Read-only shipment drill-through for monthly supplier reconciliation."""
from calendar import monthrange
from datetime import date
from decimal import Decimal
import json

from django.db.models import Sum
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from . import costs
from .cost_models import PaymentApplication, PaymentRecord, SettlementRecord
from .models import (BusinessEvent, DispatchAllocation, DispatchMembership, InboundLine,
    InboundOrder, PurchaseOrder, ShipmentLine, SupplierShipment)
from .monthly_drill_payments import difference_choices, payment_details
from .shipment_sources import source_order_ids
from .permissions import VIEW, internal_orders
from .shipment_sources import accessible_shipments
from .views import InternalAPI


class DrilldownQuery(serializers.Serializer):
    shipment_id = serializers.IntegerField(min_value=1)
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$")

    def validate_month(self, value):
        if not 1900 <= int(value[:4]) <= 9998:
            raise serializers.ValidationError("月份年份须在 1900 至 9998 之间。")
        return value


def _money(value):
    return None if value is None else str(value)


def _net_records(query, cutoff=None):
    return list(query.filter(date__lte=cutoff).order_by("date", "id") if cutoff
                else query.order_by("date", "id"))


def _signed_total(rows):
    return sum((row.amount * (Decimal("-1") if row.reverses_id else Decimal("1"))
                for row in rows), Decimal("0"))


def _line_data(line, inbound_lines, expected):
    receipts = inbound_lines.get(line.pk, [])
    counted = [row for row in receipts if row.received_quantity is not None]
    received = sum(row.received_quantity for row in counted)
    checked = sum(row.expected_quantity for row in counted)
    pending = max(0, line.quantity - checked)
    difference = received - checked if not pending else None
    return {
        "id": line.pk,
        "sku": line.sku_code_snapshot,
        "product_name": line.product_name_snapshot,
        "shipped_quantity": line.quantity,
        "unit_price": str(line.unit_price) if line.unit_price is not None else None,
        "expected_quantity": expected.get(line.pk, 0),
        "received_quantity": received,
        "difference_quantity": difference, "pending_quantity": pending,
        "progress_label": ("部分入库" if counted else "待入库") if pending else "清点完成",
        "difference_amount": str(difference * line.unit_price) if difference is not None and line.unit_price is not None else None,
        "difference_notes": [row.difference_note for row in receipts if row.difference_note],
    }


class MonthlyShipmentDrilldown(InternalAPI):
    def get(self, request):
        params = DrilldownQuery(data=request.query_params)
        params.is_valid(raise_exception=True)
        values = params.validated_data
        year, month_num = map(int, values["month"].split("-"))
        start = date(year, month_num, 1)
        cutoff = date(year, month_num, monthrange(year, month_num)[1])

        orders = internal_orders(request.user, PurchaseOrder.objects.all(), VIEW)
        shipments = accessible_shipments(orders).filter(
            tenant_id=request.user.tenant_id, status="submitted")
        shipment = shipments.filter(pk=values["shipment_id"]).select_related(
            "order", "order__supplier", "order__country").first()
        if shipment is None:
            raise NotFound("供应商发货单不可访问。")

        lines = list(ShipmentLine.objects.filter(
            tenant_id=request.user.tenant_id, shipment=shipment, is_active=True
        ).select_related("purchase_line__order").order_by("line_number"))
        line_ids = [line.pk for line in lines]
        memberships = DispatchMembership.objects.filter(
            tenant_id=request.user.tenant_id, shipment=shipment, active_guard=True,
            batch__status="active"
        ).select_related("batch", "batch__freight_company").order_by("batch_id", "id")
        batch_ids = list(memberships.values_list("batch_id", flat=True))
        allocations = list(DispatchAllocation.objects.filter(
            tenant_id=request.user.tenant_id, membership__in=memberships
        ).select_related("shipment_line"))
        inbounds = list(InboundOrder.objects.filter(
            tenant_id=request.user.tenant_id, batch_id__in=batch_ids
        ).select_related("warehouse", "stock_receipt").order_by("id"))
        inbound_lines = list(InboundLine.objects.filter(
            tenant_id=request.user.tenant_id, inbound__in=inbounds,
            inbound__status=InboundOrder.Status.CONFIRMED,
            shipment_line_id__in=line_ids
        ).select_related("inbound").order_by("inbound_id", "id"))
        by_line = {}
        for row in inbound_lines:
            by_line.setdefault(row.shipment_line_id, []).append(row)
        expected_by_line = {}
        for allocation in allocations:
            expected_by_line[allocation.shipment_line_id] = (
                expected_by_line.get(allocation.shipment_line_id, 0) + allocation.quantity)
        lines_data = [_line_data(line, by_line, expected_by_line) for line in lines]

        orders_data = [{"id": row.pk, "number": row.number, "order_date": str(row.order_date)}
                       for row in orders.filter(pk__in=source_order_ids(shipment)).order_by("id")]

        batches_data = []
        inbound_by_batch = {row.batch_id: row for row in inbounds}
        for membership in memberships:
            batch = membership.batch
            batch_allocations = [a for a in allocations if a.membership_id == membership.pk]
            inbound = inbound_by_batch.get(batch.pk)
            batches_data.append({
                "id": batch.pk, "number": batch.number,
                "freight_number": batch.freight_number,
                "container_number": batch.container_number,
                "stage": batch.stage, "departed_at": batch.departed_at,
                "arrived_warehouse_at": batch.arrived_warehouse_at,
                "allocations": [{"shipment_line_id": a.shipment_line_id,
                                 "quantity": a.quantity} for a in batch_allocations],
                "inbound": None if inbound is None else {
                    "id": inbound.pk, "number": inbound.number, "status": inbound.status,
                    "warehouse": inbound.warehouse.name,
                    "confirmed_at": inbound.confirmed_at,
                    "after_cutoff": bool(inbound.confirmed_at and inbound.confirmed_at.date() > cutoff),
                    "receipt_reference": inbound.stock_receipt.receipt_ref
                    if hasattr(inbound, "stock_receipt") else "",
                    "lines": [{
                        "shipment_line_id": row.shipment_line_id,
                        "expected_quantity": row.expected_quantity,
                        "received_quantity": row.received_quantity,
                        "difference_note": row.difference_note,
                    } for row in inbound_lines if row.inbound_id == inbound.pk],
                },
            })

        goods_due = costs.settlement_amount("shipment", shipment)
        source_number = shipment.number
        try:
            notes = json.loads(shipment.notes.splitlines()[1])
            if isinstance(notes, dict):
                source_number = notes.get("出库单号") or source_number
        except (IndexError, TypeError, ValueError):
            pass
        settlement = SettlementRecord.objects.filter(
            tenant_id=request.user.tenant_id, shipment=shipment
        ).select_related("current_revision").first()
        historical = settlement.current_revision.recorded_amount if (
            settlement and settlement.current_revision_id) else Decimal("0")
        direct = PaymentRecord.objects.filter(
            tenant_id=request.user.tenant_id, shipment=shipment, purpose="goods")
        direct_all = _net_records(direct)
        direct_at = [row for row in direct_all if row.date <= cutoff]
        applications = PaymentApplication.objects.filter(
            tenant_id=request.user.tenant_id, shipment=shipment)
        app_all = _net_records(applications.select_related("prepayment"))
        app_at = [row for row in app_all if row.date <= cutoff]
        cash_all = _signed_total(direct_all)
        cash_at = _signed_total(direct_at)
        applied_all = _signed_total(app_all)
        applied_at = _signed_total(app_at)
        settled_at = historical if settlement and settlement.current_revision_id and settlement.current_revision.date <= cutoff else Decimal("0")
        cash_history = _signed_total([row for row in direct_all if row.date < start])
        cash_month = _signed_total([row for row in direct_all if start <= row.date <= cutoff])

        revision = settlement.current_revision if settlement else None
        payments_data, domestic = payment_details(shipment, orders, direct_all, app_all, revision, cutoff)
        due_at_cutoff = goods_due if shipment.shipment_date <= cutoff else Decimal("0")

        return Response({"data": {
            "period": {"month": values["month"], "cutoff_date": str(cutoff)},
            "shipment": {
                "id": shipment.pk, "number": shipment.number,
                "source_number": source_number,
                "date": str(shipment.shipment_date),
                "supplier": shipment.order.supplier.name,
                "purchase_orders": orders_data, "lines": lines_data,
            },
            "amounts": {
                "goods_amount": str(goods_due) if goods_due is not None else None,
                "paid_cash": _money(cash_all),
                "cash_before_month": _money(cash_history),
                "cash_in_month": _money(cash_month),
                "prepayment_applied": _money(applied_all),
                "historical_paid": _money(historical),
                "remaining_at_cutoff": str(max(due_at_cutoff - cash_at - applied_at - settled_at, Decimal("0"))) if due_at_cutoff is not None else None,
                "remaining_current": str(max(goods_due - cash_all - applied_all - historical, Decimal("0"))) if goods_due is not None else None,
            },
            "batches": batches_data,
            "payments": payments_data, "domestic_freight": domestic,
            "difference_choices": difference_choices(shipment,revision),
        }})

