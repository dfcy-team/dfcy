"""Verified third-party physical snapshots, opening balances and month reconciliation."""
import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import ProductSKU, ProductCostVersion
from .monthly_cost_models import MonthlyCostInventoryEvidence, MonthlyProductCost, MonthlyCostAdjustment
from .monthly_cost_adjustments import next_month
from .monthly_cost_services import recalculate_month


def business_zone():
    return ZoneInfo(getattr(settings,"MONTHLY_PRODUCT_COST_TIMEZONE","Asia/Shanghai"))


def _quantity(value):
    try:
        result=Decimal(str(value))
    except Exception as exc:
        raise ValidationError("Invalid physical stock quantity") from exc
    if not result.is_finite() or result<0 or result.as_tuple().exponent < -4:
        raise ValidationError("Physical stock quantity must be nonnegative with at most four decimals")
    return result


@transaction.atomic
def register_inventory_evidence(*,tenant,warehouse,boundary,source_key,snapshot_at,quantities,metadata):
    if warehouse.tenant_id!=tenant.pk or boundary.day!=1 or snapshot_at.tzinfo is None:
        raise ValidationError("Inventory evidence requires matching tenant and aware month boundary")
    if not isinstance(metadata,dict) or metadata.get("complete") is not True or metadata.get("quantity_basis")!="on_hand":
        raise ValidationError("A complete physical inventory source is required")
    if not metadata.get("source_reference") or metadata.get("as_of_boundary") is not True:
        raise ValidationError("An explicit provider cutoff/source reference is required")
    boundary_at=datetime.combine(boundary,time.min,tzinfo=business_zone())
    if abs((snapshot_at-boundary_at).total_seconds())>1 and not metadata.get("verified_movement_bridge"):
        raise ValidationError("Snapshot is not at the month boundary; a verified movement bridge is required")
    if not isinstance(quantities,dict) or any(not str(key).isdigit() for key in quantities):
        raise ValidationError("Stock quantities must be keyed by internal SKU ID")
    known=set(ProductSKU.objects.filter(tenant=tenant,pk__in=quantities).values_list("pk",flat=True))
    if known!={int(key) for key in quantities}:
        raise ValidationError("Inventory evidence includes an unknown or foreign SKU")
    normalized={str(key):str(_quantity(value)) for key,value in sorted(quantities.items(),key=lambda pair:int(pair[0]))}
    digest=hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(",",":" )).encode()).hexdigest()
    record,created=MonthlyCostInventoryEvidence.objects.get_or_create(tenant=tenant,warehouse=warehouse,boundary=boundary,source_key=source_key,
        defaults=dict(snapshot_at=snapshot_at,content_hash=digest,quantities=normalized,metadata=metadata))
    if not created and (record.content_hash!=digest or record.snapshot_at!=snapshot_at or record.metadata!=metadata):
        raise ValidationError("Inventory source key was reused with different evidence")
    return record


def evidence_for(tenant_id,warehouse_id,boundary):
    rows=list(MonthlyCostInventoryEvidence.objects.filter(tenant_id=tenant_id,warehouse_id=warehouse_id,boundary=boundary).order_by("-pk"))
    if not rows:
        return None
    if len({r.content_hash for r in rows})!=1:
        raise ValidationError("Conflicting complete snapshots at the same month boundary")
    return rows[0]


def evidence_quantity(evidence,sku_id):
    if str(sku_id) in evidence.quantities:
        return _quantity(evidence.quantities[str(sku_id)])
    if evidence.metadata.get("omitted_skus_are_zero") is True:
        return Decimal(0)
    raise ValidationError("SKU is absent from the complete snapshot; zero stock is not assumed")


@transaction.atomic
def seed_opening_balances(evidence, *, unit_costs=None):
    """One-time opening from a full month-end snapshot and approved historical prices."""
    unit_costs=unit_costs or {}
    at=datetime.combine(evidence.boundary,time.min,tzinfo=business_zone())-timedelta(microseconds=1)
    prices={}
    for version in ProductCostVersion.objects.filter(tenant_id=evidence.tenant_id,warehouse_id=evidence.warehouse_id,
        status="confirmed",currency="CNY",effective_from__lte=at).order_by("sku_id","version_no"):
        if version.effective_to is None or at<version.effective_to:
            prices.setdefault(version.sku_id,[]).append(version)
    items=[]
    for key,value in evidence.quantities.items():
        sku_id=int(key);quantity=_quantity(value)
        row,created=MonthlyProductCost.objects.get_or_create(tenant_id=evidence.tenant_id,sku_id=sku_id,
            warehouse_id=evidence.warehouse_id,month=evidence.boundary)
        if row.status=="finalized":
            raise ValidationError("A finalized opening balance cannot be replaced")
        explicit=unit_costs.get(key,unit_costs.get(sku_id))
        version=prices.get(sku_id,[])
        price=_quantity(explicit) if explicit is not None else version[0].confirmed_cost if len(version)==1 else None
        amount=(quantity*price).quantize(Decimal("0.0001")) if price is not None else None
        prior_id=row.watermark.get("opening_evidence_id")
        if prior_id and row.opening_amount is not None and (row.opening_quantity!=quantity or row.opening_amount!=amount):
            raise ValidationError("Published opening evidence cannot be overwritten; register an adjustment")
        row.opening_quantity=quantity;row.opening_amount=amount
        if row.receipt_amount is None:row.receipt_amount=Decimal(0)
        if row.adjustment_amount is None:row.adjustment_amount=Decimal(0)
        row.is_complete=amount is not None
        row.missing_reason="" if amount is not None else "期初成本待补"
        row.watermark={**row.watermark,"opening_evidence_id":evidence.pk,"opening_verified":amount is not None,
            "opening_unit_cost":str(price) if price is not None else None,
            "opening_cost_version_id":version[0].pk if explicit is None and len(version)==1 else None}
        row.save();recalculate_month(row)
        items.append({"id":row.pk,"sku_id":sku_id,"complete":amount is not None})
    return {"rows":len(items),"missing":sum(not r["complete"] for r in items),"items":items}


@transaction.atomic
def reconcile_month(record):
    """Generate watermark from persisted inputs and complete physical stock evidence."""
    record=MonthlyProductCost.objects.select_for_update().get(pk=record.pk)
    if record.status=="finalized":
        return record
    record=recalculate_month(record)
    marks=dict(record.watermark);reasons=[]
    previous_month=(record.month-timedelta(days=1)).replace(day=1)
    prior=MonthlyProductCost.objects.filter(tenant_id=record.tenant_id,sku_id=record.sku_id,
        warehouse_id=record.warehouse_id,month=previous_month,status="finalized").first()
    opening=False
    if prior:
        opening=record.opening_quantity==prior.closing_quantity and record.opening_amount==prior.closing_amount
    elif marks.get("opening_evidence_id"):
        source=MonthlyCostInventoryEvidence.objects.filter(pk=marks["opening_evidence_id"],tenant_id=record.tenant_id,
            warehouse_id=record.warehouse_id,boundary=record.month).first()
        if source:
            opening=(evidence_quantity(source,record.sku_id)==record.opening_quantity and record.opening_amount is not None
                and marks.get("opening_unit_cost") is not None
                and (record.opening_quantity*Decimal(marks["opening_unit_cost"])).quantize(Decimal("0.0001"))==record.opening_amount)
    if not opening:reasons.append("期初数量和金额尚未核定")
    closing=False
    source=evidence_for(record.tenant_id,record.warehouse_id,next_month(record.month))
    if source is None:
        source=capture_wms_boundary_evidence(record.tenant,record.warehouse,next_month(record.month))
    if source:
        observed=evidence_quantity(source,record.sku_id)
        closing=observed==record.closing_quantity
        marks.update(closing_evidence_id=source.pk,observed_closing_quantity=str(observed),
            inventory_difference=str(observed-record.closing_quantity))
        if not closing:reasons.append("库存流水与第三方仓月末实存不一致")
    else:reasons.append("缺少完整月末实存快照")
    pending=MonthlyCostAdjustment.objects.filter(tenant_id=record.tenant_id,sku_id=record.sku_id,
        warehouse_id=record.warehouse_id,effective_month=record.month,status="pending").exists()
    if pending:reasons.append("跨月费用差额尚未完成来源分配")
    if not marks.get("source_complete"):reasons.append("业务流水来源存在缺口")
    if not record.is_complete:reasons.append(record.missing_reason or "成本资料不完整")
    marks.update(opening_verified=opening,inventory_reconciled=closing,adjustment_source_pending=pending,
        reconciliation_reasons=list(dict.fromkeys(reasons)))
    record.watermark=marks
    record.status="pending_review" if reasons else "estimated"
    record.missing_reason="；".join(dict.fromkeys(reasons))[:255]
    record.save()
    return recalculate_month(record)


@transaction.atomic
def capture_wms_boundary_evidence(tenant,warehouse,boundary):
    """Capture only an independently complete run with an explicit boundary cutoff.

    A successful incremental/current inventory query is insufficient. Collectors
    may certify a boundary cutoff; older providers use the reviewed import path.
    """
    from apps.commerce.models import InventorySnapshot
    from apps.integrations.models import SyncRun
    runs=SyncRun.objects.filter(tenant=tenant,status="success",failed_count=0,finished_at__isnull=False,
        sync_job__warehouse_authorization__warehouse=warehouse,sync_job__resource_type="inventory_snapshot",
        masked_log__decision_source__started_from_initial_cursor=True,
        masked_log__decision_source__ended_without_cursor=True,
        masked_log__decision_source__all_records_valid=True,
        masked_log__monthly_cost_boundary=boundary.isoformat()).order_by("-finished_at","-pk")
    run=runs.first()
    if run is None:
        return None
    facts=list(InventorySnapshot.objects.filter(tenant=tenant,warehouse=warehouse,source_run=run))
    if not facts or len(facts)!=run.fetched_count or any(r.internal_sku_id is None or "on_hand_qty" not in r.provided_quantity_fields for r in facts):
        raise ValidationError("WMS full batch count, SKU mapping or physical quantity is incomplete")
    if len({r.internal_sku_id for r in facts})!=len(facts):
        raise ValidationError("Multiple provider rows map to the same SKU; normalization requires review")
    cutoff=run.masked_log.get("monthly_cost_cutoff")
    from django.utils.dateparse import parse_datetime
    stamp=parse_datetime(cutoff or "")
    if not stamp:
        raise ValidationError("WMS must certify the exact boundary cutoff")
    return register_inventory_evidence(tenant=tenant,warehouse=warehouse,boundary=boundary,
        source_key=f"wms-run:{run.pk}",snapshot_at=stamp,
        quantities={str(r.internal_sku_id):str(r.on_hand_qty) for r in facts},metadata={
            "complete":True,"quantity_basis":"on_hand","source_reference":f"SyncRun:{run.pk}",
            "as_of_boundary":True,"source_run_id":run.pk,"row_count":len(facts),"omitted_skus_are_zero":False})
