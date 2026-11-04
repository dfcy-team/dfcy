"""Exact, tenant-scoped SKU links for incoming sales API facts; never rewrite source codes."""
from django.db.models import Q

from apps.integrations.models import IntegrationAuditLog
from apps.products.models import ProductLegacyItem, ProductSKU, ProductSKUAlias
from apps.products.sku_aliases import code_key


def resolve_sales_skus(*, tenant, store, codes, occurred_at):
    codes = {str(code or '').strip() for code in codes} - {''}
    if not codes:
        return {}
    skus = list(ProductSKU.objects.filter(tenant=tenant, spu__tenant=tenant).filter(
        Q(sku_code__in=codes) | Q(legacy_sku_code__in=codes)))
    legacy = list(ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code__in=codes,
        status=ProductLegacyItem.Status.GENERATED, generated_sku__tenant=tenant,
        generated_sku__spu__tenant=tenant).select_related('generated_sku'))
    aliases = list(ProductSKUAlias.objects.filter(tenant=tenant, sku__tenant=tenant,
        sku__spu__tenant=tenant, code_key__in={code_key(code) for code in codes}).filter(
        Q(scope_type='tenant') | Q(scope_type='store', store=store)).select_related('sku'))
    resolved = {}
    for code in codes:
        # Python equality avoids case-insensitive database collation. An alias
        # history disables the undated legacy fallback, even in an uncovered gap.
        dated = [alias for alias in aliases if alias.alias_code == code]
        candidates = {sku.id: sku for sku in skus if sku.sku_code == code}
        if dated:
            candidates.update({alias.sku_id: alias.sku for alias in dated
                if occurred_at is not None and alias.effective_from <= occurred_at
                and (alias.effective_to is None or occurred_at < alias.effective_to)})
        else:
            candidates.update({sku.id: sku for sku in skus if sku.legacy_sku_code == code})
            candidates.update({row.generated_sku_id: row.generated_sku for row in legacy
                               if row.legacy_sku_code == code})
        resolved[code] = next(iter(candidates.values())) if len(candidates) == 1 else None
    return resolved


def order_sku_fields(line, sku):
    if sku is None or (line is not None and line.internal_sku_id is not None):
        return {}
    if line is not None:
        if line.internal_spu_id not in (None, sku.spu_id):
            return {}
        linked = [*line.refund_items.all(), *line.shipment_records.all()]
        if any(item.internal_sku_id not in (None, sku.id) for item in linked):
            return {}
    return {'internal_sku_id': sku.id, 'internal_spu_id': sku.spu_id}


def audit_sku_links(source_run, changes, conflicts=None):
    if changes:
        IntegrationAuditLog.objects.create(tenant=source_run.tenant,
            integration_config=source_run.sync_job.integration_config,
            actor=source_run.sync_job.integration_config.created_by,
            action='api_sales_sku_link', result=IntegrationAuditLog.Result.SUCCESS,
            masked_detail={'source_run_id': source_run.id,
                           'rule': 'unique_exact_new_old_or_effective_alias_or_original_item',
                           'changes': changes})
    if conflicts:
        IntegrationAuditLog.objects.create(tenant=source_run.tenant,
            integration_config=source_run.sync_job.integration_config,
            actor=source_run.sync_job.integration_config.created_by,
            action='api_sales_sku_conflict', result=IntegrationAuditLog.Result.BLOCKED,
            masked_detail={'source_run_id': source_run.id, 'conflicts': conflicts})


def link_order_skus(order, source_run):
    """Fill only missing links when an unchanged order is collected again."""
    lines = list(order.items.select_for_update().prefetch_related('refund_items', 'shipment_records'))
    resolved = resolve_sales_skus(tenant=order.tenant, store=order.store,
        codes=[line.seller_sku for line in lines if line.internal_sku_id is None],
        occurred_at=order.created_at_utc)
    changes = []
    for line in lines:
        fields = order_sku_fields(line, resolved.get(line.seller_sku.strip()))
        if not fields:
            continue
        for name, value in fields.items():
            setattr(line, name, value)
        line.save(update_fields=['internal_sku', 'internal_spu'])
        changes.append({'model': 'SalesOrderItem', 'id': line.id, 'before_internal_sku_id': None,
                        'after_internal_sku_id': line.internal_sku_id})
    audit_sku_links(source_run, changes)
    return len(changes)
