"""Synchronously import the explicitly approved pilot advertiser set."""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.integrations.tiktok_ads_pilot import _validated_scope, sync_seven_complete_days
from apps.audit.models import OperationLog


class Command(BaseCommand):
    help = "Preview or import seven complete days for explicit enabled Ads mappings. Does not enable switches."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--store-id", type=int, action="append", required=True)
        parser.add_argument("--mapping-id", type=int, action="append", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(
                pk=options["actor_id"], tenant_id=options["tenant_id"],
                is_active=True, user_type="internal",
            )
            if any(not check_user_permission(actor, permission) for permission in (
                "integrations.run_live_readonly", "integrations.store.view",
            )):
                raise ValueError("action_denied")
            mappings, _ = _validated_scope(
                options["tenant_id"], options["store_id"], mapping_ids=options["mapping_id"],
            )
            if any(not integration_values_allowed(
                actor, "integrations.run_live_readonly", platform="tiktok",
                regions=[mapping.store.country_code], store_id=mapping.store_id,
            ) for mapping in mappings):
                raise ValueError("store_scope_denied")
        except Exception:
            raise CommandError("ads_selected_scope_rejected") from None
        receipt = {
            "mode": "preview", "accounts": len(mappings), "report_scope": "AUCTION_CAMPAIGN",
            "days": 7, "database_writes": 0,
        }
        if options["apply"]:
            audit = OperationLog.objects.create(
                tenant_id=actor.tenant_id, user=actor, module="integrations",
                action="sync", object_type="tiktok_ads_selected", object_id="pilot",
                after_data={"status": "started", "mapping_ids": sorted(options["mapping_id"]),
                            "store_ids": sorted(options["store_id"]), "report_scope": "AUCTION_CAMPAIGN"},
            )
            try:
                results = sync_seven_complete_days(
                    tenant_id=actor.tenant_id, approved_store_ids=options["store_id"],
                    approved_mapping_ids=options["mapping_id"],
                )
            except Exception as exc:
                audit.after_data = {**audit.after_data, "status": "failed", "error_type": type(exc).__name__}
                audit.save(update_fields=["after_data"])
                raise CommandError("ads_selected_sync_failed:" + type(exc).__name__) from None
            receipt.update(mode="apply", days_written=sum(r["days_written"] for r in results),
                           missing_account_days=sum(len(r["missing_days"]) for r in results))
            del receipt["database_writes"]
            audit.after_data = {**audit.after_data, "status": "completed", **receipt}
            audit.save(update_fields=["after_data"])
        self.stdout.write(json.dumps(receipt, sort_keys=True))
