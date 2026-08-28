import csv
import io
import re
import unicodedata
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import NotificationMessage
from apps.common.exceptions import ScopedResourceNotFound, StateConflict
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster, SupplierMaster, SupplierStatusChoices
from apps.products.coding_services import allocate_spu_code, build_sku_code, category_path
from apps.products.models import ProductCategory, ProductColor, ProductResearch, ProductSKU, ProductSPU

from .models import (
    DevelopmentCostEstimate,
    DevelopmentPerformanceReview,
    DevelopmentProductArchive,
    DevelopmentProductArchiveEvent,
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


def _resolve_archive_category(*, tenant, project, explicit=None, fallback=None):
    category = explicit or getattr(project, "category_node", None) or fallback
    category_id = getattr(category, "pk", category)
    category = ProductCategory.objects.select_related("parent__parent").filter(pk=category_id).first()
    if category is None or category.tenant_id != tenant.id:
        raise ValidationError({"category_node": "Category does not belong to the current tenant."})
    if not category.is_active or category.level != ProductCategory.Level.L3:
        raise ValidationError({"category_node": "An active L3 product category is required."})
    try:
        category_path(category)
    except Exception as exc:
        raise ValidationError({"category_node": str(exc)}) from exc
    return category


def _resolve_archive_market(*, tenant, data, existing=None):
    """Resolve structured platform/store records and synchronized snapshots.

    The archive predates master-data references, so plain ``platform``/``site``
    strings remain valid for legacy/internal trials.  Once a structured record
    is supplied, it is always checked against the current tenant and active
    status, and the snapshots are derived from the selected records.
    """
    data = data or {}
    platform = data.get("platform_master", data.get("platform_id", getattr(existing, "platform_master", None)))
    store = data.get("store_master", data.get("store_id", getattr(existing, "store_master", None)))

    if platform is not None and not isinstance(platform, PlatformMaster):
        platform_id = platform
        platform = PlatformMaster.objects.filter(pk=platform_id).first()
        if platform is None:
            raise ValidationError({"platform_master": "Platform is outside the current tenant or does not exist."})
    if store is not None and not isinstance(store, StoreMaster):
        store_id = store
        store = StoreMaster.objects.select_related("platform").filter(pk=store_id).first()
        if store is None:
            raise ValidationError({"store_master": "Store is outside the current tenant or does not exist."})
    if platform is not None:
        if platform.tenant_id != tenant.id or platform.status != StatusChoices.ACTIVE:
            raise ValidationError({"platform_master": "Platform must be active and belong to the current tenant."})
    if store is not None:
        if store.tenant_id != tenant.id or store.status != StatusChoices.ACTIVE:
            raise ValidationError({"store_master": "Store must be active and belong to the current tenant."})
        if platform is None:
            platform = store.platform
            if platform.tenant_id != tenant.id or platform.status != StatusChoices.ACTIVE:
                raise ValidationError({"platform_master": "Platform must be active and belong to the current tenant."})
        if store.platform_id != platform.id:
            raise ValidationError({"store_master": "Store must belong to the selected platform."})

    raw_platform = data.get("platform", getattr(existing, "platform", "internal"))
    raw_site = data.get("site", getattr(existing, "site", "internal"))
    snapshot_platform = str(raw_platform or "internal").strip() or "internal"
    snapshot_site = str(raw_site or "internal").strip() or "internal"
    if platform is not None:
        if snapshot_platform.lower() not in {"internal", str(platform.code).strip().lower()}:
            raise ValidationError({"platform": "Platform snapshot must match the selected platform."})
        snapshot_platform = str(platform.code).strip()
    if store is not None:
        country = str(store.country_code or "").strip().upper()
        if snapshot_site.lower() not in {"internal", country.lower()}:
            raise ValidationError({"site": "Site must match the selected store country."})
        snapshot_site = country
    return platform, store, snapshot_platform, snapshot_site


_DEV_CODE_RE = re.compile(r"^[A-Z0-9]+$")


def _normalize_development_code(value, *, field="development_spu_code"):
    """Normalize and validate a developer-controlled code segment."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    if not normalized:
        raise ValidationError({field: "A development SPU code is required."})
    if not re.search(r"[A-Z]", normalized) or any(char.isspace() for char in normalized) or not _DEV_CODE_RE.fullmatch(normalized):
        raise ValidationError({field: "Use A-Z/0-9 with at least one letter; separators and whitespace are not allowed."})
    return normalized


def _normalize_development_segment(value, *, field):
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    # Keep the segment deterministic while ensuring the SKU remains exactly
    # three hyphen-delimited logical parts even when a source value contains a
    # separator (for example ``10-12cm``).
    normalized = re.sub(r"[^A-Z0-9]+", "X", normalized).strip("X")
    if not normalized or not _DEV_CODE_RE.fullmatch(normalized):
        raise ValidationError({field: "The development SKU segment is empty after normalization."})
    return normalized


def _development_spec_code(*, category, spec_values):
    """Return a separator-safe, deterministic third development-SKU segment."""
    if not spec_values:
        return "STD", {}
    if not isinstance(spec_values, dict):
        raise ValidationError({"spec_values": "Specifications must be keyed by dimension code."})
    dimensions = category.spec_dimensions or []
    expected = [item.get("code") for item in dimensions if item.get("code")]
    unknown = set(spec_values) - set(expected)
    if unknown:
        raise ValidationError({"spec_values": f"Unknown specification dimensions: {', '.join(sorted(unknown))}."})
    normalized = {}
    segments = []
    for code in expected:
        raw = spec_values.get(code, "")
        if str(raw or "").strip() in ("", "0"):
            continue
        segment = _normalize_development_segment(raw, field="spec_values")
        configured = next((item.get("values") or [] for item in dimensions if item.get("code") == code), [])
        if configured and str(raw).strip() not in configured:
            raise ValidationError({"spec_values": f"Specification value for {code} is not configured for this category."})
        normalized[code] = str(raw).strip()
        segments.append(segment)
    return ("X".join(segments) if segments else "STD"), normalized


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


def _record_product_archive_event(*, archive, actor, action, from_status="", to_status="", metadata=None):
    return DevelopmentProductArchiveEvent.objects.create(
        archive=archive,
        tenant=archive.tenant,
        action=action,
        from_status=from_status or "",
        to_status=to_status or "",
        actor=actor,
        metadata=metadata or {},
    )


@transaction.atomic
def create_product_archive(*, project_id, actor, data=None):
    data = data or {}
    project = (
        DevelopmentProject.objects.select_for_update()
        .select_related("tenant", "category_node")
        .filter(pk=project_id, tenant=actor.tenant)
        .first()
    )
    if project is None:
        raise ScopedResourceNotFound("Development project is not available in the current tenant.")
    if project.status == DevelopmentProject.Status.CANCELLED:
        raise StateConflict("A cancelled development project cannot create a product archive.")
    category = _resolve_archive_category(
        tenant=project.tenant,
        project=project,
        explicit=data.get("category_node"),
    )
    platform, store, snapshot_platform, snapshot_site = _resolve_archive_market(
        tenant=project.tenant,
        data=data,
    )
    existing = DevelopmentProductArchive.objects.select_for_update().filter(project=project).first()
    if existing is not None:
        comparisons = {field: data.get(field) for field in ("product_name",)}
        if existing.category_node_id != category.pk or any(
            value is not None and str(value) != str(getattr(existing, field))
            for field, value in comparisons.items()
        ):
            raise StateConflict("A product archive already exists for this project with different values.")
        if platform is not None and existing.platform_master_id not in (None, platform.pk):
            raise StateConflict("A product archive already exists with a different platform master.")
        if store is not None and existing.store_master_id not in (None, store.pk):
            raise StateConflict("A product archive already exists with a different store master.")
        if data.get("platform") is not None and str(existing.platform).lower() != snapshot_platform.lower():
            raise StateConflict("A product archive already exists with a different platform snapshot.")
        if data.get("site") is not None and str(existing.site).lower() != snapshot_site.lower():
            raise StateConflict("A product archive already exists with a different site snapshot.")
        return existing, False
    target_sites = project.target_sites if isinstance(project.target_sites, list) else []
    if data.get("site") is None and store is None and target_sites:
        snapshot_site = str(target_sites[0] or "internal").strip() or "internal"
    archive_no = _next_code(DevelopmentProductArchive, project.tenant, "archive_no", "DPA")
    archive = DevelopmentProductArchive.objects.create(
        tenant=project.tenant,
        project=project,
        archive_no=archive_no,
        product_name=str(data.get("product_name") or project.product_name).strip(),
        category=category.name,
        category_node=category,
        platform_master=platform,
        store_master=store,
        platform=snapshot_platform,
        site=snapshot_site,
        virtual_inventory_sku=str(data.get("virtual_inventory_sku") or f"VT-{archive_no}").strip(),
        virtual_inventory_qty=max(int(data.get("virtual_inventory_qty") or 0), 0),
        test_notes=str(data.get("test_notes") or "").strip(),
        created_by=actor,
        updated_by=actor,
    )
    _record_product_archive_event(
        archive=archive,
        actor=actor,
        action="created",
        to_status=archive.status,
        metadata={
            "platform": snapshot_platform,
            "site": snapshot_site,
            "platform_master_id": platform.pk if platform else None,
            "store_master_id": store.pk if store else None,
            "virtual_inventory_sku": archive.virtual_inventory_sku,
        },
    )
    return archive, True


@transaction.atomic
def update_product_archive(*, archive_id, actor, data):
    archive = (
        DevelopmentProductArchive.objects.select_for_update()
        .select_related("project", "platform_master", "store_master")
        .filter(pk=archive_id, tenant=actor.tenant)
        .first()
    )
    if archive is None:
        raise ScopedResourceNotFound("Product archive is not available in the current tenant.")
    if archive.status != DevelopmentProductArchive.Status.TRIAL:
        raise StateConflict("Only a virtual trial archive can be edited.")
    category = _resolve_archive_category(
        tenant=archive.tenant,
        project=archive.project,
        explicit=data.get("category_node"),
        fallback=archive.category_node,
    )
    platform, store, snapshot_platform, snapshot_site = _resolve_archive_market(
        tenant=archive.tenant,
        data=data,
        existing=archive,
    )
    changed = {}
    for field in ("product_name", "virtual_inventory_qty", "test_notes"):
        if field not in data:
            continue
        value = max(int(data[field] or 0), 0) if field == "virtual_inventory_qty" else data[field]
        value = value.strip() if isinstance(value, str) else value
        if value != getattr(archive, field):
            setattr(archive, field, value)
            changed[field] = value
    if archive.platform_master_id != getattr(platform, "pk", None):
        archive.platform_master = platform
        changed["platform_master"] = getattr(platform, "pk", None)
    if archive.store_master_id != getattr(store, "pk", None):
        archive.store_master = store
        changed["store_master"] = getattr(store, "pk", None)
    if "platform" in data and archive.platform != snapshot_platform:
        archive.platform = snapshot_platform
        changed["platform"] = snapshot_platform
    elif platform is not None and archive.platform != snapshot_platform:
        archive.platform = snapshot_platform
        changed["platform"] = snapshot_platform
    if "site" in data and archive.site != snapshot_site:
        archive.site = snapshot_site
        changed["site"] = snapshot_site
    elif store is not None and archive.site != snapshot_site:
        archive.site = snapshot_site
        changed["site"] = snapshot_site
    if archive.category_node_id != category.pk or archive.category != category.name:
        archive.category_node = category
        archive.category = category.name
        changed.update({"category_node": category.pk, "category": category.name})
    if changed:
        archive.updated_by = actor
        archive.save(update_fields=[*changed.keys(), "updated_by", "updated_at"])
        _record_product_archive_event(
            archive=archive,
            actor=actor,
            action="updated",
            from_status=archive.status,
            to_status=archive.status,
            metadata={"changes": changed},
        )
    return archive


@transaction.atomic
def generate_trial_product(*, archive_id, actor, data=None, idempotency_key=""):
    """Create (or replay) the draft/not-listed SPU/SKU used for platform tests.

    A row-level archive lock makes retries safe.  The generated development
    identifiers are persisted on the archive and remain separate from the
    official product identifiers created during formalization.
    """
    data = data or {}
    archive = (
        DevelopmentProductArchive.objects.select_for_update()
        .select_related("project", "category_node", "trial_product", "trial_sku")
        .filter(pk=archive_id, tenant=actor.tenant)
        .first()
    )
    if archive is None:
        raise ScopedResourceNotFound("Product archive is not available in the current tenant.")
    if archive.status not in {DevelopmentProductArchive.Status.TRIAL, DevelopmentProductArchive.Status.CONFIRMED}:
        if archive.status == DevelopmentProductArchive.Status.FORMALIZED and archive.formal_product_id:
            return archive, False
        raise StateConflict("Only a trial or confirmed archive can generate a trial product.")

    category = _resolve_archive_category(
        tenant=archive.tenant,
        project=archive.project,
        explicit=archive.category_node,
    )
    development_spu_code = _normalize_development_code(data.get("development_spu_code"), field="development_spu_code")
    season_code = str(data.get("season_code") or getattr(archive, "season_code", "0") or "0").strip()
    if not re.fullmatch(r"[0-9]", season_code):
        raise ValidationError({"season_code": "Attribute code must be one digit."})
    # A complete existing pair is the idempotent replay path.  Reject a caller
    # that tries to alter color/specification after the SKU was generated.
    if archive.trial_product_id and archive.trial_sku_id:
        if archive.trial_product.tenant_id != archive.tenant_id or archive.trial_sku.tenant_id != archive.tenant_id or archive.trial_sku.spu_id != archive.trial_product_id:
            raise StateConflict("The stored trial product references are outside the archive tenant.")
        if archive.trial_product.spu_code != development_spu_code:
            raise StateConflict("The trial development SPU code cannot change after generation.")
        requested_color = str(data.get("color_code") or "").strip()
        requested_specs = data.get("spec_values")
        if requested_color and requested_color != archive.trial_sku.color_code:
            raise StateConflict("The trial SKU color cannot change after generation.")
        if requested_specs is not None and requested_specs != (archive.trial_sku.spec_values or {}):
            raise StateConflict("The trial SKU specifications cannot change after generation.")
        return archive, False
    if archive.trial_product_id and not archive.trial_sku_id:
        trial_spu = archive.trial_product
        if trial_spu.tenant_id != archive.tenant_id:
            raise StateConflict("The stored trial product belongs to another tenant.")
        if trial_spu.spu_code != development_spu_code:
            raise StateConflict("The trial development SPU code cannot change after generation.")
    else:
        if DevelopmentProductArchive.objects.filter(
            tenant=archive.tenant,
            development_spu_code=development_spu_code,
        ).exclude(pk=archive.pk).exists() or ProductSPU.objects.filter(
            tenant=archive.tenant,
            spu_code=development_spu_code,
        ).exists():
            raise ValidationError({"development_spu_code": "This development SPU code is already used in the current tenant."})
        trial_spu = ProductSPU.objects.create(
            tenant=archive.tenant,
            spu_code=development_spu_code,
            product_name=archive.product_name,
            category=category.name,
            category_node=category,
            l1_code="",
            l2_code="",
            l3_code="",
            season_code=season_code,
            lifecycle_status=ProductSPU.LifecycleStatus.DRAFT,
            sales_status=ProductSPU.SalesStatus.NOT_LISTED,
        )

    color_code = str(data.get("color_code") or "").strip()
    if not color_code:
        # Keep the one-click operation useful for tenants with a single active
        # color, while still requiring an explicit choice when ambiguous.
        active_colors = list(ProductColor.objects.filter(tenant=archive.tenant, is_active=True).order_by("code")[:2])
        if len(active_colors) == 1:
            color_code = active_colors[0].code
        else:
            raise ValidationError({"color_code": "An active tenant color is required to generate a trial SKU."})
    color = ProductColor.objects.filter(tenant=archive.tenant, code=color_code, is_active=True).first()
    if color is None:
        raise ValidationError({"color_code": "Select an active color from the current tenant dictionary."})
    spec_values = data.get("spec_values", {})
    if spec_values is None:
        spec_values = {}
    specification, normalized = _development_spec_code(category=category, spec_values=spec_values)
    color_segment = _normalize_development_segment(color.code, field="color_code")
    sku_code = f"{development_spu_code}-{color_segment}-{specification}"
    if sku_code.count("-") != 2 or len(sku_code) > 80:
        raise ValidationError({"development_spu_code": "The generated development SKU must be three segments and at most 80 characters."})
    if ProductSKU.objects.filter(tenant=archive.tenant, sku_code=sku_code).exclude(pk=archive.trial_sku_id).exists():
        raise ValidationError({"development_spu_code": "This development SKU code is already used in the current tenant."})
    trial_sku = ProductSKU.objects.create(
        tenant=archive.tenant,
        spu=trial_spu,
        sku_code=sku_code,
        product_name=archive.product_name,
        color_code=color.code,
        specification=specification,
        spec_values=normalized,
        size=specification,
        is_active=True,
    )
    archive.trial_product = trial_spu
    archive.trial_sku = trial_sku
    archive.category_node = category
    archive.category = category.name
    archive.updated_by = actor
    archive.development_spu_code = development_spu_code
    archive.season_code = season_code
    archive.save(update_fields=["development_spu_code", "season_code", "trial_product", "trial_sku", "category_node", "category", "updated_by", "updated_at"])
    _record_product_archive_event(
        archive=archive,
        actor=actor,
        action="trial_product_generated",
        from_status=archive.status,
        to_status=archive.status,
        metadata={
            "trial_product_id": trial_spu.id,
            "trial_spu_code": trial_spu.spu_code,
            "trial_sku_id": trial_sku.id,
            "trial_sku_code": trial_sku.sku_code,
            "color_code": trial_sku.color_code,
            "spec_values": trial_sku.spec_values,
            "idempotency_key": idempotency_key or "",
        },
    )
    return archive, True


@transaction.atomic
def confirm_product_archive(*, archive_id, actor, test_result="pass", test_notes=None, idempotency_key=""):
    archive = DevelopmentProductArchive.objects.select_for_update().filter(pk=archive_id, tenant=actor.tenant).first()
    if archive is None:
        raise ScopedResourceNotFound("Product archive is not available in the current tenant.")
    if archive.status in {DevelopmentProductArchive.Status.CONFIRMED, DevelopmentProductArchive.Status.FORMALIZED}:
        return archive, False
    if archive.status != DevelopmentProductArchive.Status.TRIAL:
        raise StateConflict("Only a virtual trial archive can be confirmed.")
    result = str(test_result or "pass").strip().lower()
    if result != DevelopmentProductArchive.TestResult.PASS:
        raise StateConflict("Only a passed virtual test can be confirmed.")
    previous_status = archive.status
    archive.test_result = result
    if test_notes is not None:
        archive.test_notes = str(test_notes).strip()
    archive.status = DevelopmentProductArchive.Status.CONFIRMED
    archive.trial_confirmed_by = actor
    archive.trial_confirmed_at = timezone.now()
    archive.updated_by = actor
    archive.save(update_fields=["test_result", "test_notes", "status", "trial_confirmed_by", "trial_confirmed_at", "updated_by", "updated_at"])
    _record_product_archive_event(
        archive=archive,
        actor=actor,
        action="trial_confirmed",
        from_status=previous_status,
        to_status=archive.status,
        metadata={"idempotency_key": idempotency_key or ""},
    )
    return archive, True


@transaction.atomic
def formalize_product_archive(*, archive_id, actor, idempotency_key=""):
    archive = (
        DevelopmentProductArchive.objects.select_for_update()
        .select_related("project", "formal_product", "formal_sku", "trial_product", "trial_sku")
        .filter(pk=archive_id, tenant=actor.tenant)
        .first()
    )
    if archive is None:
        raise ScopedResourceNotFound("Product archive is not available in the current tenant.")
    if archive.status == DevelopmentProductArchive.Status.FORMALIZED:
        return archive.formal_product, False
    if archive.status != DevelopmentProductArchive.Status.CONFIRMED:
        raise StateConflict("A product archive must be trial-confirmed before formalization.")
    if not archive.trial_product_id or not archive.trial_sku_id:
        raise StateConflict("Generate and retain a development trial SPU/SKU before formalization.")
    if archive.trial_product.tenant_id != archive.tenant_id or archive.trial_sku.tenant_id != archive.tenant_id or archive.trial_sku.spu_id != archive.trial_product_id:
        raise StateConflict("The development trial product references are outside the archive tenant.")
    project = DevelopmentProject.objects.select_for_update().select_related("finalized_product", "category_node").get(pk=archive.project_id)
    category = _resolve_archive_category(tenant=archive.tenant, project=project, explicit=archive.category_node)
    if project.finalized_product_id and project.finalized_product_id != archive.trial_product_id:
        raise StateConflict("The development project already points to a different formal product.")
    # Trial products intentionally remain in the development namespace.  A
    # confirmed archive always receives a new official SPU.
    product = None
    created = False
    if product is None:
        season_code = str(archive.season_code or "0").strip() or "0"
        try:
            spu_code, segments = allocate_spu_code(
                tenant=archive.tenant,
                category=category,
                season_code=season_code,
            )
        except DjangoValidationError as exc:
            raise ValidationError({"season_code": exc.messages}) from exc
        product = ProductSPU.objects.create(
            tenant=archive.tenant,
            spu_code=spu_code,
            product_name=archive.product_name,
            category=category.name,
            category_node=category,
            l1_code=segments[0],
            l2_code=segments[1],
            l3_code=segments[2],
            season_code=season_code,
            lifecycle_status=ProductSPU.LifecycleStatus.DRAFT,
            sales_status=ProductSPU.SalesStatus.NOT_LISTED,
        )
        created = True
    elif product.tenant_id != archive.tenant_id:
        raise StateConflict("The linked formal product belongs to another tenant.")
    formal_sku = archive.formal_sku
    if archive.trial_sku_id:
        try:
            sku_code, specification, normalized = build_sku_code(
                spu=product,
                color_code=archive.trial_sku.color_code,
                spec_values=archive.trial_sku.spec_values or {},
            )
        except DjangoValidationError as exc:
            raise ValidationError({"spec_values": exc.messages}) from exc
        formal_sku = ProductSKU.objects.filter(tenant=archive.tenant, sku_code=sku_code).first()
        if formal_sku is None:
            formal_sku = ProductSKU.objects.create(
                tenant=archive.tenant,
                spu=product,
                sku_code=sku_code,
                product_name=archive.product_name,
                color_code=archive.trial_sku.color_code,
                specification=specification,
                spec_values=normalized,
                size=specification,
                is_active=True,
            )
        elif formal_sku.spu_id != product.id:
            raise StateConflict("The generated formal SKU belongs to another product.")
    now = timezone.now()
    project.stage = DevelopmentProject.Stage.FINALIZED
    project.finalized_product = product
    project.save(update_fields=["stage", "finalized_product", "updated_at"])
    previous_status = archive.status
    archive.formal_product = product
    archive.formal_sku = formal_sku
    archive.category_node = category
    archive.category = category.name
    archive.status = DevelopmentProductArchive.Status.FORMALIZED
    archive.formalized_by = actor
    archive.formalized_at = now
    archive.updated_by = actor
    archive.save(update_fields=["formal_product", "formal_sku", "category_node", "category", "status", "formalized_by", "formalized_at", "updated_by", "updated_at"])
    _record_product_archive_event(
        archive=archive,
        actor=actor,
        action="formalized",
        from_status=previous_status,
        to_status=archive.status,
        metadata={
            "product_id": product.id,
            "spu_code": product.spu_code,
            "trial_product_id": archive.trial_product_id,
            "formal_sku_id": formal_sku.id if formal_sku else None,
            "formal_sku_code": formal_sku.sku_code if formal_sku else "",
            "created": created,
            "idempotency_key": idempotency_key or "",
        },
    )
    return product, created


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
