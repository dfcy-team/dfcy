import hashlib
import secrets
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import (
    ProductBundleChangeAudit,
    ProductBundleComponent,
    ProductBundleMigrationBatch,
    ProductBundleVersion,
    ProductBundleVersionComponent,
    ProductSKU,
    ProductSPU,
)


def component_payload(rows):
    return [
        {"component_sku_id": row.component_sku_id, "component_sku_code": row.component_sku.sku_code, "quantity": row.quantity}
        for row in rows
    ]


def create_bundle_version(*, bundle_sku, actor, effective_at=None, reason="", action="components_updated", before=None):
    components = list(bundle_sku.bundle_components.select_related("component_sku", "component_sku__spu"))
    next_version = (bundle_sku.bundle_versions.aggregate(value=Max("version"))["value"] or 0) + 1
    version = ProductBundleVersion.objects.create(
        tenant=bundle_sku.tenant,
        bundle_sku=bundle_sku,
        version=next_version,
        effective_at=effective_at or timezone.now(),
        reason=reason,
        created_by=actor,
    )
    ProductBundleVersionComponent.objects.bulk_create([
        ProductBundleVersionComponent(
            version=version,
            component_sku=row.component_sku,
            component_sku_code=row.component_sku.sku_code,
            component_name=row.component_sku.product_name or row.component_sku.spu.product_name,
            quantity=row.quantity,
        ) for row in components
    ])
    after = component_payload(components)
    ProductBundleChangeAudit.objects.create(
        tenant=bundle_sku.tenant, bundle_sku=bundle_sku, version=version, action=action,
        reason=reason, before_payload=before or [], after_payload=after, actor=actor,
    )
    return version


def validate_component_rows(tenant, rows, bundle_sku=None):
    if not rows:
        raise ValueError("components must not be empty")
    ids = [int(row["component_sku_id"] if "component_sku_id" in row else row["component_sku"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate component SKU")
    skus = {sku.id: sku for sku in ProductSKU.objects.select_related("spu").filter(tenant=tenant, id__in=ids, is_active=True)}
    if len(skus) != len(ids):
        raise ValueError("component SKU not found or inactive")
    for sku_id in ids:
        if skus[sku_id].spu.product_type == ProductSPU.ProductType.BUNDLE or (bundle_sku and sku_id == bundle_sku.id):
            raise ValueError("nested or self-referencing bundles are not supported")
    normalized = []
    for row, sku_id in zip(rows, ids):
        quantity = int(row["quantity"])
        if quantity < 1:
            raise ValueError("component quantity must be positive")
        normalized.append((skus[sku_id], quantity))
    return normalized


def preview_legacy_migration(*, tenant, actor, rows):
    grouped = defaultdict(list)
    errors = []
    for index, row in enumerate(rows, start=1):
        try:
            key = (str(row["legacy_bundle_spu"]).strip(), str(row["legacy_bundle_sku"]).strip())
            component = str(row["legacy_component_sku"]).strip()
            quantity = int(row["quantity"])
            if not all((*key, component)) or quantity < 1:
                raise ValueError
            grouped[key].append((component, quantity))
        except (KeyError, TypeError, ValueError):
            errors.append({"row": index, "code": "invalid_row"})
    normalized = []
    for (legacy_spu, legacy_sku), components in grouped.items():
        bundle_matches = list(ProductSKU.objects.select_related("spu").filter(
            tenant=tenant, legacy_sku_code=legacy_sku, spu__legacy_spu_code=legacy_spu
        )[:2])
        if len(bundle_matches) != 1:
            errors.append({"legacy_bundle_sku": legacy_sku, "code": "bundle_not_unique"})
            continue
        resolved = []
        seen = set()
        for legacy_component, quantity in components:
            matches = list(ProductSKU.objects.filter(tenant=tenant, legacy_sku_code=legacy_component)[:2])
            if len(matches) != 1:
                errors.append({"legacy_bundle_sku": legacy_sku, "legacy_component_sku": legacy_component, "code": "component_not_unique"})
                continue
            if matches[0].id == bundle_matches[0].id or matches[0].id in seen:
                errors.append({"legacy_bundle_sku": legacy_sku, "legacy_component_sku": legacy_component, "code": "self_or_duplicate"})
                continue
            seen.add(matches[0].id)
            resolved.append({"component_sku_id": matches[0].id, "quantity": quantity})
        if len(resolved) == len(components):
            normalized.append({"bundle_sku_id": bundle_matches[0].id, "components": resolved})
    raw_token = secrets.token_urlsafe(32)
    batch = ProductBundleMigrationBatch.objects.create(
        tenant=tenant, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), created_by=actor,
        normalized_rows=normalized,
        preview_summary={"input_rows": len(rows), "bundles_ready": len(normalized), "error_count": len(errors), "errors": errors[:20]},
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return raw_token, batch


@transaction.atomic
def confirm_legacy_migration(*, tenant, actor, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    batch = ProductBundleMigrationBatch.objects.select_for_update().filter(tenant=tenant, token_hash=token_hash).first()
    if not batch or batch.status != batch.Status.PREVIEWED or batch.expires_at <= timezone.now():
        raise ValueError("preview token is invalid, expired, or already consumed")
    if batch.preview_summary.get("error_count"):
        raise ValueError("preview contains errors")
    for item in batch.normalized_rows:
        bundle = ProductSKU.objects.select_for_update().select_related("spu").get(tenant=tenant, pk=item["bundle_sku_id"])
        before = component_payload(bundle.bundle_components.select_related("component_sku"))
        normalized = validate_component_rows(tenant, item["components"], bundle)
        bundle.spu.product_type = ProductSPU.ProductType.BUNDLE
        bundle.spu.save(update_fields=["product_type", "updated_at"])
        bundle.bundle_components.all().delete()
        for component, quantity in normalized:
            ProductBundleComponent.objects.create(tenant=tenant, bundle_sku=bundle, component_sku=component, quantity=quantity)
        create_bundle_version(bundle_sku=bundle, actor=actor, reason="legacy ZH migration", action="legacy_migrated", before=before)
    batch.status = batch.Status.CONFIRMED
    batch.confirmed_at = timezone.now()
    batch.save(update_fields=["status", "confirmed_at"])
    return batch
