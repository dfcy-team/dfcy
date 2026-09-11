"""Explicit, audited backfill of existing inventory facts; never starts a sync."""

import json
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import IntegrationAuditLog
from apps.masterdata.models import WarehouseMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.products.models import ProductSKU


class Command(BaseCommand):
    help = "Preview exact legacy SKU links for a warehouse; --apply requires the expected match count."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--warehouse-id", type=int, required=True)
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
            raise CommandError("An active same-tenant integration administrator with all scope is required.")
        if not WarehouseMaster.objects.filter(pk=options["warehouse_id"], tenant_id=tenant_id).exists():
            raise CommandError("Warehouse must belong to the selected tenant.")
        if options["apply"] and options["expected_matches"] is None:
            raise CommandError("--apply requires --expected-matches from a reviewed preview.")

        # Python equality is intentional: database collations may ignore case.
        legacy = defaultdict(set)
        current = defaultdict(set)
        skus = ProductSKU.objects.filter(tenant_id=tenant_id).order_by("pk")
        if options["apply"]:
            skus = skus.select_for_update()
        for sku in skus:
            current[sku.sku_code].add(sku.id)
            if sku.legacy_sku_code:
                legacy[sku.legacy_sku_code].add(sku.id)

        rows = InventorySnapshot.objects.filter(
            tenant_id=tenant_id, warehouse_id=options["warehouse_id"], internal_sku__isnull=True,
        ).order_by("pk")
        if options["apply"]:
            rows = rows.select_for_update()
        matches = []
        unmatched = []
        conflicts = []
        for row in rows:
            candidates = legacy[row.source_sku]
            if not candidates:
                unmatched.append(row.source_sku)
                continue
            competing = current[row.source_sku]
            if row.seller_sku and row.seller_sku != row.source_sku:
                conflicts.append(row.source_sku)
            elif len(candidates) != 1 or (competing and competing != candidates):
                conflicts.append(row.source_sku)
            else:
                matches.append((row, next(iter(candidates))))

        if options["apply"]:
            if len(matches) != options["expected_matches"]:
                raise CommandError("Match count changed; review a new preview before applying.")
            changes = defaultdict(list)
            for row, sku_id in matches:
                row.internal_sku_id = sku_id
                row.save(update_fields=["internal_sku"])
                changes[row.source_run.sync_job.integration_config_id].append({
                    "snapshot_id": row.id, "before_internal_sku_id": None, "after_internal_sku_id": sku_id,
                })
            for config_id, detail in changes.items():
                IntegrationAuditLog.objects.create(
                    tenant_id=tenant_id, integration_config_id=config_id, actor=actor,
                    action="inventory_legacy_sku_link", result=IntegrationAuditLog.Result.SUCCESS,
                    masked_detail={"warehouse_id": options["warehouse_id"],
                                   "rule": "source_sku_exact_unique_legacy_sku", "changes": detail},
                )
        self.stdout.write(json.dumps({
            "applied": options["apply"], "matched": len(matches),
            "unmatched": sorted(set(unmatched)), "conflicts": sorted(set(conflicts)),
        }, ensure_ascii=False))
