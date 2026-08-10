import csv
import io
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import NotificationMessage
from apps.common.exceptions import ScopedResourceNotFound, StateConflict
from apps.masterdata.models import SupplierMaster, SupplierStatusChoices
from apps.products.models import ProductResearch, ProductSPU

from .models import (
    DevelopmentCostEstimate,
    DevelopmentPerformanceReview,
    DevelopmentProject,
    DevelopmentProjectStage,
    DevelopmentRequirementChangeLog,
    DevelopmentSample,
    ProductSalesSnapshot,
)


STAGE_TRANSITIONS = {
    DevelopmentProject.Stage.INITIATED: DevelopmentProject.Stage.DESIGN,
    DevelopmentProject.Stage.DESIGN: DevelopmentProject.Stage.SAMPLING,
    DevelopmentProject.Stage.SAMPLING: DevelopmentProject.Stage.REVIEW,
}


def _normalize_name(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").casefold())


def check_duplicate_requirement(*, tenant, product_name, category="", exclude_id=None, threshold=Decimal("0.65")):
    normalized = _normalize_name(product_name)
    if not normalized:
        raise ValidationError({"product_name": "Product name is required."})
    queryset = ProductResearch.objects.filter(tenant=tenant)
    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)
    matches = []
    for item in queryset.only("id", "research_no", "product_name", "approval_status"):
        score = Decimal(str(SequenceMatcher(None, normalized, _normalize_name(item.product_name)).ratio()))
        if score >= threshold:
            matches.append({
                "id": item.id,
                "research_no": item.research_no,
                "product_name": item.product_name,
                "status": item.approval_status,
                "similarity": score.quantize(Decimal("0.0001")),
            })
    return sorted(matches, key=lambda row: row["similarity"], reverse=True)


def _next_code(model, tenant, field, prefix):
    date_part = timezone.localdate().strftime("%Y%m%d")
    base = f"{prefix}-{date_part}-"
    latest = model.objects.filter(tenant=tenant, **{f"{field}__startswith": base}).order_by(f"-{field}").first()
    sequence = 1
    if latest:
        try:
            sequence = int(getattr(latest, field).rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            pass
    return f"{base}{sequence:03d}"


@transaction.atomic
def advance_project_stage(*, project_id, actor, target_stage, approval_notes="", deliverables=None):
    project = DevelopmentProject.objects.select_for_update().filter(pk=project_id, tenant=actor.tenant).first()
    if project is None:
        raise ScopedResourceNotFound("Development project is not available in the current tenant.")
    expected = STAGE_TRANSITIONS.get(project.stage)
    if target_stage != expected:
        raise StateConflict(f"Project stage must advance from {project.stage} to {expected}.")
    if target_stage == DevelopmentProject.Stage.REVIEW and not project.samples.exists():
        raise StateConflict("At least one sample record is required before review.")
    now = timezone.now()
    DevelopmentProjectStage.objects.filter(project=project, stage=project.stage, completed_at__isnull=True).update(completed_at=now)
    DevelopmentProjectStage.objects.create(
        project=project,
        stage=target_stage,
        entered_at=now,
        deliverables=deliverables or {},
        approved_by=actor,
        approval_notes=approval_notes,
    )
    project.stage = target_stage
    project.save(update_fields=["stage", "updated_at"])
    return project


@transaction.atomic
def finalize_product(*, project_id, actor):
    project = DevelopmentProject.objects.select_for_update().filter(pk=project_id, tenant=actor.tenant).first()
    if project is None:
        raise ScopedResourceNotFound("Development project is not available in the current tenant.")
    if project.finalized_product_id:
        return project.finalized_product, False
    if project.stage != DevelopmentProject.Stage.REVIEW:
        raise StateConflict("Only a project in review can be finalized.")
    if not project.samples.filter(evaluation_result=DevelopmentSample.Evaluation.PASS).exists():
        raise StateConflict("At least one passed sample is required before finalization.")
    if not project.cost_estimates.filter(status=DevelopmentCostEstimate.Status.APPROVED).exists():
        raise StateConflict("At least one approved cost estimate is required before finalization.")

    product = ProductSPU.objects.create(
        tenant=project.tenant,
        spu_code=_next_code(ProductSPU, project.tenant, "spu_code", "SPU"),
        product_name=project.product_name,
        category=project.category,
        development_source=project.development_source,
        development_project=project,
    )
    now = timezone.now()
    DevelopmentProjectStage.objects.filter(
        project=project,
        stage=DevelopmentProject.Stage.REVIEW,
        completed_at__isnull=True,
    ).update(completed_at=now)
    DevelopmentProjectStage.objects.create(
        project=project,
        stage=DevelopmentProject.Stage.FINALIZED,
        entered_at=now,
        approved_by=actor,
        approval_notes="Product finalized and product master created.",
        deliverables={"product_id": product.id, "spu_code": product.spu_code},
    )
    project.stage = DevelopmentProject.Stage.FINALIZED
    project.finalized_product = product
    project.save(update_fields=["stage", "finalized_product", "updated_at"])
    NotificationMessage.objects.create(
        tenant=project.tenant,
        user=project.assigned_to,
        title=f"商品定型成功：{project.product_name}",
        message=f"开发项目 {project.project_no} 已定型，商品编码：{product.spu_code}。",
        message_type="development_product_finalized",
    )
    if project.requirement_id:
        DevelopmentRequirementChangeLog.objects.create(
            requirement=project.requirement,
            changed_by=actor,
            change_type="product_finalized",
            field_name="approval_status",
            old_value=project.requirement.approval_status,
            new_value="finalized",
        )
    return product, True


@transaction.atomic
def get_or_create_trial_supplier(*, tenant, name, actor, contact_email="", contact_phone=""):
    name = (name or "").strip()
    if not name:
        raise ValidationError({"name": "Supplier name is required."})
    query = SupplierMaster.objects.select_for_update().filter(tenant=tenant, name__iexact=name)
    if contact_email:
        query = query.filter(contact_email__iexact=contact_email)
    elif contact_phone:
        query = query.filter(contact_phone=contact_phone)
    existing = query.first()
    if existing:
        return existing, False
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code=_next_code(SupplierMaster, tenant, "code", "trial-supplier").lower(),
        name=name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        status=SupplierStatusChoices.TRIAL,
    )
    return supplier, True


@transaction.atomic
def calculate_cost_summary(*, estimate_id, actor, approve=False):
    estimate = DevelopmentCostEstimate.objects.select_for_update().select_related("project").filter(
        pk=estimate_id, project__tenant=actor.tenant
    ).first()
    if estimate is None:
        raise ScopedResourceNotFound("Cost estimate is not available in the current tenant.")
    direct = sum((
        estimate.material_cost,
        estimate.processing_fee,
        estimate.packaging_cost,
        estimate.first_leg_shipping,
        estimate.other_cost,
    ), Decimal("0"))
    selling_fees = estimate.target_selling_price * (
        estimate.platform_commission_rate + estimate.tariff_rate
    )
    estimate.total_cost = direct + selling_fees
    estimate.estimated_margin = estimate.target_selling_price - estimate.total_cost
    estimate.estimated_margin_rate = (
        estimate.estimated_margin / estimate.target_selling_price
        if estimate.target_selling_price
        else Decimal("0")
    )
    if approve:
        estimate.status = DevelopmentCostEstimate.Status.APPROVED
        estimate.approved_by = actor
    estimate.save(update_fields=[
        "total_cost", "estimated_margin", "estimated_margin_rate", "status", "approved_by"
    ])
    return estimate


def _decimal(row, key, default="0"):
    try:
        return Decimal((row.get(key) or default).strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError({key: "A valid decimal value is required."})


@transaction.atomic
def import_sales_csv(*, tenant, csv_text, actor):
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    required = {"spu_code", "site", "platform", "snapshot_date", "daily_sales_qty"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValidationError({"csv": f"Required columns: {', '.join(sorted(required))}."})
    created = updated = 0
    for line_number, row in enumerate(reader, start=2):
        product = ProductSPU.objects.filter(tenant=tenant, spu_code=(row.get("spu_code") or "").strip()).first()
        if product is None:
            raise ValidationError({"csv": f"Unknown SPU on line {line_number}."})
        try:
            snapshot_date = timezone.datetime.strptime(row["snapshot_date"].strip(), "%Y-%m-%d").date()
            quantity = int(row["daily_sales_qty"])
        except (ValueError, TypeError):
            raise ValidationError({"csv": f"Invalid date or quantity on line {line_number}."})
        _, was_created = ProductSalesSnapshot.objects.update_or_create(
            tenant=tenant,
            product=product,
            site=row["site"].strip(),
            snapshot_date=snapshot_date,
            defaults={
                "platform": row["platform"].strip(),
                "daily_sales_qty": quantity,
                "daily_sales_amount": _decimal(row, "daily_sales_amount"),
                "daily_sales_amount_usd": _decimal(row, "daily_sales_amount_usd"),
                "cumulative_sales_qty": int(row.get("cumulative_sales_qty") or 0),
                "cumulative_sales_amount_usd": _decimal(row, "cumulative_sales_amount_usd"),
                "current_price": _decimal(row, "current_price") if row.get("current_price") else None,
                "review_count": int(row.get("review_count") or 0),
                "rating": _decimal(row, "rating") if row.get("rating") else None,
                "ad_spend": _decimal(row, "ad_spend"),
                "data_source": ProductSalesSnapshot.Source.MANUAL,
            },
        )
        created += int(was_created)
        updated += int(not was_created)
    return {"created": created, "updated": updated, "total": created + updated}


def review_reminder_candidates(*, tenant, as_of=None):
    as_of = as_of or timezone.localdate()
    candidates = []
    projects = DevelopmentProject.objects.filter(
        tenant=tenant,
        actual_launch_date__isnull=False,
        finalized_product__isnull=False,
    ).select_related("requirement", "finalized_product")
    for project in projects:
        elapsed = (as_of - project.actual_launch_date).days
        for days in (30, 90):
            period = f"launch_{days}d"
            if elapsed >= days and not DevelopmentPerformanceReview.objects.filter(project=project, review_period=period).exists():
                candidates.append({"project_id": project.id, "product_id": project.finalized_product_id, "review_period": period, "due_date": project.actual_launch_date + timedelta(days=days)})
    return candidates
