import json

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import ScopedResourceNotFound, StateConflict
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSPU
from apps.rpa.models import RPATask

from .models import (
    ListingChangeLog,
    ListingProfile,
    ListingPublicationJob,
    ListingTask,
    ListingTaskStepLog,
    ListingVariant,
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
    return errors


@transaction.atomic
def validate_listing(*, profile_id, actor, persist=True):
    """Validate a tenant-owned draft and optionally persist its ready status."""
    profile = ListingProfile.objects.select_for_update().filter(pk=profile_id, tenant=actor.tenant).first()
    if profile is None:
        raise ScopedResourceNotFound("Listing profile is not available in the current tenant.")
    errors = validate_listing_profile(profile)
    if persist:
        profile.validation_errors = errors
        if errors:
            profile.status = ListingProfile.Status.DRAFT
        elif profile.status == ListingProfile.Status.DRAFT:
            profile.status = ListingProfile.Status.READY
        profile.save(update_fields=["validation_errors", "status", "updated_at"])
    return profile, errors


@transaction.atomic
def generate_listing_drafts(*, tenant, actor, spu_ids, store_ids, sku_ids=None, **_kwargs):
    """Create deterministic, tenant-scoped listing drafts for selected products/stores."""
    try:
        spu_ids = [int(value) for value in spu_ids]
        store_ids = [int(value) for value in store_ids]
        sku_ids = {int(value) for value in (sku_ids or [])}
    except (TypeError, ValueError):
        raise ValidationError({"selection": "SPU, store, and SKU ids must be integers."})
    if not spu_ids or not store_ids:
        raise ValidationError({"selection": "At least one SPU and one store are required."})
    spus = list(ProductSPU.objects.filter(tenant=tenant, id__in=spu_ids).prefetch_related("skus"))
    stores = list(StoreMaster.objects.filter(tenant=tenant, id__in=store_ids))
    if len(spus) != len(set(spu_ids)):
        raise ValidationError({"spu_ids": "One or more SPUs are not available in the current tenant."})
    if len(stores) != len(set(store_ids)):
        raise ValidationError({"store_ids": "One or more stores are not available in the current tenant."})
    profiles = []
    for spu in spus:
        for store in stores:
            profile_no = f"LST-{spu.id}-{store.id}"
            profile, _created = ListingProfile.objects.get_or_create(
                tenant=tenant,
                profile_no=profile_no,
                defaults={
                    "product": spu,
                    "store": store,
                    "title": spu.product_name,
                    "currency": store.currency,
                    "created_by": actor,
                },
            )
            # A retry must not overwrite an approved/published draft.
            existing = set(profile.variants.values_list("sku_id", flat=True))
            for sku in spu.skus.all():
                if not sku.is_active or (sku_ids and sku.id not in sku_ids) or sku.id in existing:
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
    return profiles


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
            {"sku_id": item.sku_id, "seller_sku": item.seller_sku, "price": str(item.price), "stock_quantity": item.stock_quantity, "attributes": item.attributes}
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
    if execution_mode == ListingPublicationJob.ExecutionMode.PRODUCTION and not confirm_production:
        raise ValidationError({"confirm_production": "Production publication requires explicit confirmation."})
    profile = ListingProfile.objects.select_for_update().filter(pk=profile_id, tenant=actor.tenant).first()
    if profile is None:
        raise ScopedResourceNotFound("Listing profile is not available in the current tenant.")
    existing = ListingPublicationJob.objects.filter(tenant=actor.tenant, idempotency_key=idempotency_key).first()
    if existing:
        if existing.profile_id != profile.id or existing.action != action:
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
    rpa_task = RPATask.objects.create(
        tenant=actor.tenant,
        task_type="listing.publish",
        business_type="listing",
        business_id=str(profile.id),
        payload={"action": action, "profile_id": profile.id, "listing": payload},
    )
    job.rpa_task = rpa_task
    job.save(update_fields=["rpa_task"])
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
