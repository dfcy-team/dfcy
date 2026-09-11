"""Explicit, audited association of existing sales facts; no platform requests."""
import json
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.commerce.models import SalesOrderItem, RefundReturnItem
from apps.integrations.models import IntegrationAuditLog
from apps.listings.models import PlatformProductDetail
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.products.models import ProductSKU, ProductLegacyItem


class Command(BaseCommand):
    help = "Preview unique exact sales SKU links; apply only a reviewed match count."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-matches", type=int)

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        actor = get_user_model().objects.filter(pk=options["actor_id"], tenant_id=tenant_id).first()
        permission = "integrations.manage"
        if not check_user_permission(actor, permission) or not any(
            scope["scope_type"] == "all" for scope in get_permission_data_scopes(actor, permission)
        ):
            raise CommandError("A same-tenant integration administrator with all scope is required.")
        if options["apply"] and options["expected_matches"] is None:
            raise CommandError("Apply requires a reviewed expected match count.")

        # Python equality deliberately avoids case-insensitive MySQL collations.
        codes = defaultdict(set)
        skus = {sku.id: sku for sku in ProductSKU.objects.select_for_update().filter(tenant_id=tenant_id)}
        for sku in skus.values():
            for code in (sku.sku_code, sku.legacy_sku_code):
                if code:
                    codes[code].add(sku.id)
        for code, sku_id in ProductLegacyItem.objects.filter(
            tenant_id=tenant_id, status=ProductLegacyItem.Status.GENERATED,
            generated_sku__tenant_id=tenant_id,
        ).values_list("legacy_sku_code", "generated_sku_id"):
            if code:
                codes[code].add(sku_id)
        variants = defaultdict(set)
        for detail in PlatformProductDetail.objects.filter(
            tenant_id=tenant_id, internal_sku__tenant_id=tenant_id,
        ):
            variants[(detail.store_id, detail.platform_id, detail.platform_product_id,
                      detail.platform_variant_id)].add(detail.internal_sku_id)

        matches, skipped, proposed = [], defaultdict(list), {}
        for model, parent_name in ((SalesOrderItem, "sales_order"), (RefundReturnItem, "refund_return")):
            rows = model.objects.select_for_update().filter(**{
                f"{parent_name}__tenant_id": tenant_id, "internal_sku__isnull": True,
            }).select_related(parent_name)
            if model is RefundReturnItem:
                rows = rows.select_related("sales_order_item__sales_order")
            for row in rows.order_by("pk"):
                parent = getattr(row, parent_name)
                targets = set(codes.get(row.seller_sku, ()))
                targets.update(codes.get(row.seller_sku.strip(), ()))
                if row.platform_variant_id:
                    targets.update(variants.get((parent.store_id, parent.platform_id,
                                                 row.platform_product_id, row.platform_variant_id), ()))
                if model is SalesOrderItem:
                    targets.update(row.refund_items.exclude(internal_sku=None).values_list("internal_sku_id", flat=True))
                    targets.update(row.shipment_records.exclude(internal_sku=None).values_list("internal_sku_id", flat=True))
                elif row.sales_order_item_id:
                    linked = row.sales_order_item
                    if linked.sales_order.tenant_id != tenant_id or linked.sales_order_id != parent.sales_order_id:
                        skipped["conflict"].append(row.seller_sku)
                        continue
                    linked_id = linked.internal_sku_id or proposed.get(linked.id)
                    if linked_id:
                        targets.add(linked_id)
                sku = skus.get(next(iter(targets))) if len(targets) == 1 else None
                if sku is None or (model is SalesOrderItem and row.internal_spu_id not in (None, sku.spu_id)):
                    skipped["conflict" if targets else "unmatched"].append(row.seller_sku)
                    continue
                matches.append((row, parent, sku))
                if model is SalesOrderItem:
                    proposed[row.id] = sku.id

        if options["apply"]:
            if len(matches) != options["expected_matches"]:
                raise CommandError("Match count changed; review a fresh preview.")
            changes = defaultdict(list)
            for row, parent, sku in matches:
                fields = ["internal_sku"]
                row.internal_sku = sku
                before_spu = getattr(row, "internal_spu_id", None)
                if isinstance(row, SalesOrderItem):
                    row.internal_spu_id = sku.spu_id
                    fields.append("internal_spu")
                row.save(update_fields=fields)
                changes[parent.source_run.sync_job.integration_config_id].append({
                    "model": row._meta.model_name, "id": row.id,
                    "before_internal_sku_id": None, "after_internal_sku_id": sku.id,
                    "before_internal_spu_id": before_spu,
                })
            for config_id, detail in changes.items():
                IntegrationAuditLog.objects.create(
                    tenant_id=tenant_id, actor=actor, integration_config_id=config_id,
                    action="sales_sku_link", result=IntegrationAuditLog.Result.SUCCESS,
                    masked_detail={"rule": "unique_exact_catalogue_or_same_store_variant_or_linked_item", "changes": detail},
                )
        self.stdout.write(json.dumps({
            "applied": options["apply"], "matched": len(matches),
            "orders": sum(isinstance(row, SalesOrderItem) for row, _, _ in matches),
            "refunds": sum(isinstance(row, RefundReturnItem) for row, _, _ in matches),
            "skipped_counts": {key: len(value) for key, value in skipped.items()},
            "skipped_codes": {key: sorted(set(value)) for key, value in skipped.items()},
        }, ensure_ascii=False))
