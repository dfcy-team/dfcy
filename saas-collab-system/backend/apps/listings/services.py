import json
from itertools import product as cartesian_product
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import ScopedResourceNotFound, StateConflict
from apps.rpa.models import RPATask
from apps.products.models import ProductSKU, ProductSPU
from apps.masterdata.models import StoreMaster

from .models import (
    ListingAttributeMapping,
    ListingChangeLog,
    ListingProfile,
    ListingPublicationJob,
    ListingTask,
    ListingTaskErrorLog,
    ListingTaskStepLog,
    ListingTemplate,
    ListingVariant,
    PlatformCategoryMapping,
)


def validate_listing_profile(profile):
    errors = []
    if not profile.title.strip():
        errors.append({"field": "title", "message": "Title is required."})
    if profile.price is None or profile.price <= 0:
        errors.append({"field": "price", "message": "A positive price is required."})
    if not profile.currency:
        errors.append({"field": "currency", "message": "Currency is required."})
    if not profile.variants.exists():
        errors.append({"field": "variants", "message": "At least one SKU variant is required."})
    if not profile.media:
        errors.append({"field": "media", "message": "At least one product image is required."})
    if profile.product_id and profile.product.tenant_id != profile.tenant_id:
        errors.append({"field": "product", "message": "Product does not belong to the listing tenant."})
    if profile.store_id and profile.store.tenant_id != profile.tenant_id:
        errors.append({"field": "store", "message": "Store does not belong to the listing tenant."})
    if profile.template_id and profile.template.tenant_id != profile.tenant_id:
        errors.append({"field": "template", "message": "Template does not belong to the listing tenant."})
    for variant in profile.variants.select_related("sku").all():
        if variant.sku.tenant_id != profile.tenant_id or variant.sku.spu_id != profile.product_id:
            errors.append({"field": "variants", "message": f"SKU {variant.sku_id} is not linked to this SPU."})
    # Required mapped fields are checked against the draft payload without
    # mutating the source product model.
    if profile.template_id:
        required = ListingAttributeMapping.objects.filter(
            tenant_id=profile.tenant_id,
            platform_id=profile.template.platform_id,
            template_id=profile.template_id,
            country_code=profile.store.country_code,
            status=ListingAttributeMapping.Status.ACTIVE,
            is_required=True,
        )
        for mapping in required:
            value = profile.attributes.get(mapping.target_attribute_code)
            if value in (None, "", [], {}):
                errors.append({
                    "field": f"attributes.{mapping.target_attribute_code}",
                    "message": f"Required attribute {mapping.target_attribute_name or mapping.target_attribute_code} is missing.",
                })
    return errors


@transaction.atomic
def validate_listing(*, profile_id, actor, persist=True):
    profile = ListingProfile.objects.select_for_update().filter(pk=profile_id, tenant=actor.tenant).first()
    if profile is None:
        raise ScopedResourceNotFound("Listing profile is not available in the current tenant.")
    errors = validate_listing_profile(profile)
    if persist:
        profile.validation_errors = errors
        if not errors and profile.status == ListingProfile.Status.DRAFT:
            profile.status = ListingProfile.Status.READY
        elif errors and profile.status == ListingProfile.Status.READY:
            profile.status = ListingProfile.Status.DRAFT
        profile.save(update_fields=["validation_errors", "status", "updated_at"])
    return profile, errors


@transaction.atomic
def submit_listing_for_approval(*, profile_id, actor):
    profile = ListingProfile.objects.select_for_update().filter(pk=profile_id, tenant=actor.tenant).first()
    if profile is None:
        raise ScopedResourceNotFound("Listing profile is not available in the current tenant.")
    if profile.status not in {ListingProfile.Status.DRAFT, ListingProfile.Status.READY, ListingProfile.Status.FAILED}:
        raise StateConflict("Only a draft, ready, or failed listing can be submitted.")
    errors = validate_listing_profile(profile)
    before = profile.status
    profile.validation_errors = errors
    if errors:
        profile.save(update_fields=["validation_errors", "updated_at"])
        raise ValidationError({"listing": errors})
    profile.status = ListingProfile.Status.PENDING_APPROVAL
    profile.save(update_fields=["status", "validation_errors", "updated_at"])
    ListingChangeLog.objects.create(profile=profile, changed_by=actor, action="submit", before_snapshot={"status": before}, after_snapshot={"status": profile.status})
    return profile


def _profile_no(product, store, template=None):
    template_part = f"-T{template.id}" if template else "-T0"
    return f"LST-{product.id}-{store.id}{template_part}"


def _draft_payload(profile):
    return {
        "profile_id": profile.id,
        "profile_no": profile.profile_no,
        "tenant_id": profile.tenant_id,
        "store_id": profile.store_id,
        "product_id": profile.product_id,
        "spu_code": profile.product.spu_code,
        "legacy_spu_code": profile.product.legacy_spu_code,
        "brand": profile.product.brand,
        "status": profile.status,
    }


@transaction.atomic
def generate_listing_drafts(*, tenant, actor, spu_ids, store_ids, template_id=None, template_ids=None, sku_ids=None, idempotency_key=""):
    """Create tenant-scoped profile drafts for SPU × store × template selections.

    Existing deterministic profile numbers are reused, making retries safe even
    when the browser loses the response after a successful transaction.
    """
    if not spu_ids or not store_ids:
        raise ValidationError({"selection": "At least one SPU and one store are required."})
    try:
        spu_ids = [int(value) for value in spu_ids]
        store_ids = [int(value) for value in store_ids]
        selected_sku_ids = {int(value) for value in (sku_ids or [])}
    except (TypeError, ValueError):
        raise ValidationError({"selection": "SPU, store, and SKU ids must be integers."})
    spus = list(ProductSPU.objects.filter(tenant=tenant, id__in=spu_ids).prefetch_related("skus"))
    stores = list(StoreMaster.objects.filter(tenant=tenant, id__in=store_ids).select_related("platform"))
    if len(spus) != len(set(spu_ids)):
        raise ValidationError({"spu_ids": "One or more SPUs are not available in the current tenant."})
    if len(stores) != len(set(store_ids)):
        raise ValidationError({"store_ids": "One or more stores are not available in the current tenant."})
    templates_qs = ListingTemplate.objects.filter(tenant=tenant, is_active=True).select_related("platform")
    if template_ids:
        try:
            template_ids = [int(value) for value in template_ids]
        except (TypeError, ValueError):
            raise ValidationError({"template_ids": "Template ids must be integers."})
        templates_qs = templates_qs.filter(id__in=template_ids)
    elif template_id:
        templates_qs = templates_qs.filter(id=int(template_id))
    templates = list(templates_qs)
    if not templates:
        # A template is optional for backwards compatibility with manually
        # created profiles; one draft per SPU/store is still useful.
        templates = [None]
    profiles = []
    for spu, store, template in cartesian_product(spus, stores, templates):
        if template is not None and template.platform_id != store.platform_id:
            continue
        profile_no = _profile_no(spu, store, template)
        profile = ListingProfile.objects.filter(tenant=tenant, profile_no=profile_no).first()
        if profile is None:
            title = spu.product_name
            category_code = (template.category_code if template else "") or spu.category or ""
            source_category_code = spu.category or (spu.category_node.code if spu.category_node_id else "")
            category_mapping = PlatformCategoryMapping.objects.filter(
                tenant=tenant,
                platform=store.platform,
                country_code=store.country_code,
                source_category_code=source_category_code,
                status=PlatformCategoryMapping.Status.ACTIVE,
            ).order_by("-mapping_version").first()
            if category_mapping:
                category_code = category_mapping.target_category_code
            profile = ListingProfile.objects.create(
                tenant=tenant,
                profile_no=profile_no,
                product=spu,
                store=store,
                template=template,
                title=title,
                category_code=category_code,
                attributes=dict(template.default_values) if template else {},
                currency=store.currency,
                created_by=actor,
            )
        elif profile.status not in {ListingProfile.Status.DRAFT, ListingProfile.Status.READY, ListingProfile.Status.FAILED}:
            # Never overwrite approved/published data on a retry.
            profiles.append(profile)
            continue
        existing_skus = set(profile.variants.values_list("sku_id", flat=True))
        selected = [sku for sku in spu.skus.all() if sku.is_active and (not selected_sku_ids or sku.id in selected_sku_ids)]
        for sku in selected:
            if sku.id in existing_skus:
                continue
            ListingVariant.objects.create(
                profile=profile,
                sku=sku,
                seller_sku=sku.sku_code,
                price=sku.purchase_price or 0,
                attributes={
                    "color_code": sku.color_code,
                    "specification": sku.specification,
                    "spec_values": sku.spec_values,
                },
            )
        profiles.append(profile)
    if not profiles:
        raise ValidationError({"selection": "No compatible SPU/store/template combinations were found."})
    return profiles


@transaction.atomic
def approve_listing(*, profile_id, actor):
    profile = ListingProfile.objects.select_for_update().filter(pk=profile_id, tenant=actor.tenant).first()
    if profile is None:
        raise ScopedResourceNotFound("Listing profile is not available in the current tenant.")
    if profile.status != ListingProfile.Status.PENDING_APPROVAL:
        raise StateConflict("Only a pending listing can be approved.")
    profile.status = ListingProfile.Status.APPROVED
    profile.approved_by = actor
    profile.approved_at = timezone.now()
    profile.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    ListingChangeLog.objects.create(profile=profile, changed_by=actor, action="approve", before_snapshot={"status": ListingProfile.Status.PENDING_APPROVAL}, after_snapshot={"status": profile.status})
    return profile


def _publication_payload(profile):
    return {
        "profile_no": profile.profile_no,
        "store_id": profile.store_id,
        "product_id": profile.product_id,
        "title": profile.title,
        "description": profile.description,
        "category_code": profile.category_code,
        "attributes": profile.attributes,
        "media": profile.media,
        "price": str(profile.price),
        "currency": profile.currency,
        "variants": [
            {
                "sku_id": item.sku_id,
                "sku_code": item.sku.sku_code,
                "legacy_sku_code": item.sku.legacy_sku_code,
                "color_code": item.sku.color_code,
                "specification": item.sku.specification,
                "purchase_price": str(item.sku.purchase_price) if item.sku.purchase_price is not None else None,
                "seller_sku": item.seller_sku,
                "price": str(item.price),
                "stock_quantity": item.stock_quantity,
                "attributes": item.attributes,
            }
            for item in profile.variants.all()
        ],
    }


@transaction.atomic
def queue_listing_publication(
    *,
    profile_id,
    actor,
    idempotency_key,
    action=ListingPublicationJob.Action.CREATE,
    execution_mode=ListingPublicationJob.ExecutionMode.DRY_RUN,
    execution_channel=ListingPublicationJob.ExecutionChannel.RPA,
    confirm_production=False,
):
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key is required."})
    if action not in ListingPublicationJob.Action.values:
        raise ValidationError({"action": "Unsupported publication action."})
    if execution_mode not in ListingPublicationJob.ExecutionMode.values:
        raise ValidationError({"execution_mode": "Unsupported execution mode."})
    if execution_channel not in ListingPublicationJob.ExecutionChannel.values:
        raise ValidationError({"execution_channel": "Unsupported execution channel."})
    if execution_mode == ListingPublicationJob.ExecutionMode.PRODUCTION and confirm_production is not True:
        raise ValidationError({"confirm_production": "Production publication requires explicit confirmation."})
    profile = ListingProfile.objects.select_for_update().filter(pk=profile_id, tenant=actor.tenant).first()
    if profile is None:
        raise ScopedResourceNotFound("Listing profile is not available in the current tenant.")
    existing = ListingPublicationJob.objects.filter(tenant=actor.tenant, idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.profile_id != profile.id
            or existing.action != action
            or existing.execution_mode != execution_mode
            or existing.execution_channel != execution_channel
        ):
            raise StateConflict("The idempotency key was used for a different publication request.")
        return existing, True
    if profile.status != ListingProfile.Status.APPROVED:
        raise StateConflict("Only an approved listing can be queued for publication.")
    payload = _publication_payload(profile)
    job = ListingPublicationJob.objects.create(
        tenant=actor.tenant,
        profile=profile,
        action=action,
        idempotency_key=idempotency_key,
        payload_snapshot=payload,
        requested_by=actor,
        execution_mode=execution_mode,
        execution_channel=execution_channel,
        confirmed_production=bool(confirm_production),
    )
    # The RPA record is an internal queue envelope only.  No platform API or
    # browser is contacted here; an agent may execute it later.
    rpa_task = None
    if execution_channel == ListingPublicationJob.ExecutionChannel.RPA:
        rpa_task = RPATask.objects.create(
            tenant=actor.tenant,
            task_type="listing.publish",
            business_type="listing",
            business_id=str(profile.id),
            execution_mode=execution_mode,
            payload={"action": action, "profile_id": profile.id, "profile_no": profile.profile_no, "listing": payload},
        )
    task = ListingTask.objects.create(
        tenant=actor.tenant,
        task_no=f"LST-TASK-{job.id:08d}",
        profile=profile,
        publication_job=job,
        execution_channel=execution_channel,
        execution_mode=execution_mode,
        idempotency_key=idempotency_key,
        payload_snapshot=payload,
        confirmed_production=bool(confirm_production),
        rpa_task=rpa_task,
        requested_by=actor,
    )
    if rpa_task is not None:
        job.rpa_task = rpa_task
        job.save(update_fields=["rpa_task"])
    ListingTaskStepLog.objects.create(
        tenant=actor.tenant,
        task=task,
        step_no=1,
        step_name="queued",
        status=ListingTaskStepLog.Status.PENDING,
        detail={"boundary": "queue_only", "external_platform_call": False},
    )
    profile.status = ListingProfile.Status.PUBLISHING
    profile.save(update_fields=["status", "updated_at"])
    ListingChangeLog.objects.create(profile=profile, changed_by=actor, action="queue_publish", before_snapshot={"status": ListingProfile.Status.APPROVED}, after_snapshot={"status": profile.status, "job_id": job.id})
    return job, False


def listing_task_snapshot(task):
    return {
        "id": task.id,
        "task_no": task.task_no,
        "profile_id": task.profile_id,
        "publication_job_id": task.publication_job_id,
        "rpa_task_id": task.rpa_task_id,
        "execution_channel": task.execution_channel,
        "execution_mode": task.execution_mode,
        "status": task.status,
        "idempotency_key": task.idempotency_key,
        "current_step": task.current_step,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "payload_snapshot": task.payload_snapshot,
        "result_snapshot": task.result_snapshot,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "steps": [
            {
                "id": row.id,
                "step_no": row.step_no,
                "step_name": row.step_name,
                "status": row.status,
                "message": row.message,
                "detail": row.detail,
                "created_at": row.created_at,
            }
            for row in task.step_logs.all()
        ],
        "errors": [
            {
                "id": row.id,
                "error_code": row.error_code,
                "message": row.message,
                "detail": row.detail,
                "is_resolved": row.is_resolved,
                "created_at": row.created_at,
            }
            for row in task.error_logs.all()
        ],
    }


@transaction.atomic
def fail_listing_task(*, task_id, actor, error_code, message, detail=None, step_name="publish"):
    task = ListingTask.objects.select_for_update().filter(id=task_id, tenant=actor.tenant).first()
    if task is None:
        raise ScopedResourceNotFound("Listing task is not available in the current tenant.")
    task.status = ListingTask.Status.FAILED
    task.error_code = str(error_code)[:80]
    task.error_message = str(message)
    task.finished_at = timezone.now()
    task.current_step = step_name
    task.save(update_fields=["status", "error_code", "error_message", "finished_at", "current_step", "updated_at"])
    error = ListingTaskErrorLog.objects.create(
        tenant=actor.tenant,
        task=task,
        error_code=task.error_code,
        message=task.error_message,
        detail=detail or {},
    )
    return task, error
