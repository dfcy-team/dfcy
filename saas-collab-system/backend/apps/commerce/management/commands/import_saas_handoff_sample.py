import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.accounts.models import CustomUser
from apps.commerce.services import upsert_inventory_snapshot
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
)
from apps.integrations.store_authorization_service import (
    create_store_authorization,
    transition_store_authorization,
)
from apps.integrations.store_mapping_service import create_store_mapping
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.sales_management.services import upsert_normalized_order, upsert_normalized_refund
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Idempotently import the reviewed synthetic SaaS handoff sample through application services."

    def add_arguments(self, parser):
        parser.add_argument("sample_path")
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--commit", action="store_true", help="Persist changes; default is dry-run rollback.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["sample_path"] == "-":
            payload = json.load(sys.stdin)
        else:
            path = Path(options["sample_path"]).resolve()
            if not path.is_file():
                raise CommandError(f"Sample file does not exist: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("synthetic") is not True or payload.get("schema_version") != "shopapi-handoff.v1":
            raise CommandError("Only the reviewed synthetic shopapi-handoff.v1 sample is accepted.")

        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        actor = CustomUser.objects.filter(
            pk=options["actor_id"], tenant=tenant, user_type=CustomUser.UserType.INTERNAL, is_active=True
        ).first()
        if tenant is None or actor is None:
            raise CommandError("Tenant and active internal actor must exist and belong to the same tenant.")

        platforms = {}
        for platform_code in {row["platform"] for row in payload["stores"]}:
            platform = PlatformMaster.objects.filter(tenant=tenant, platform_type=platform_code).order_by("id").first()
            if platform is None:
                raise CommandError(f"Tenant {tenant.id} has no platform master for {platform_code}.")
            platforms[platform_code] = platform

        stores = {}
        for row in payload["stores"]:
            store, _ = StoreMaster.objects.update_or_create(
                tenant=tenant,
                code=row["code"],
                defaults={
                    "platform": platforms[row["platform"]],
                    "name": row["name"],
                    "platform_store_name": row.get("platform_store_name", ""),
                    "country_code": row["country_code"],
                    "currency": row["currency"],
                    "timezone": row["timezone"],
                    "status": row.get("status", "active"),
                },
            )
            stores[row["id"]] = store

        warehouses = {}
        for row in payload["warehouses"]:
            warehouse, _ = WarehouseMaster.objects.update_or_create(
                tenant=tenant,
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "country_code": row["country_code"],
                    "warehouse_type": row["warehouse_type"],
                    "status": row.get("status", "active"),
                },
            )
            warehouses[row["id"]] = warehouse

        configs = {}
        for row in payload["integration_configs"]:
            config, _ = PlatformIntegrationConfig.objects.update_or_create(
                tenant=tenant,
                platform=row["platform"],
                account_alias=row["account_alias"],
                environment=row["environment"],
                defaults={
                    "status": PlatformIntegrationConfig.Status.VERIFIED,
                    "regions": row.get("regions", []),
                    "network_enabled": False,
                    "sync_read_enabled": False,
                    "sync_write_enabled": False,
                    "created_by": actor,
                },
            )
            configs[row["id"]] = config

        for row in payload["store_authorizations"]:
            store = stores[row["store_id"]]
            config = configs[row["config_id"]]
            authorization = MarketplaceStoreAuthorization.objects.filter(
                tenant=tenant, platform=config.platform, store=store
            ).order_by("-id").first()
            if authorization is None:
                suffix = f"{tenant.id}-{config.platform}-{store.code}".lower()
                authorization = create_store_authorization(
                    tenant=tenant,
                    integration_config=config,
                    store=store,
                    platform=config.platform,
                    region=store.country_code,
                    platform_store_id=row["platform_store_id"],
                    merchant_subject_id=f"synthetic-subject-{suffix}",
                    shop_cipher=(f"synthetic-shop-cipher-{suffix}" if config.platform == "tiktok" else ""),
                    credential_id=f"synthetic-credential-{suffix}",
                    token_id=f"synthetic-token-{suffix}",
                    scopes=[],
                    actor=actor,
                )
                authorization = transition_store_authorization(
                    authorization,
                    target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
                    actor=actor,
                )
            if not MarketplaceStoreMapping.objects.filter(tenant=tenant, authorization=authorization).exists():
                create_store_mapping(
                    tenant=tenant,
                    actor=actor,
                    store=store,
                    authorization=authorization,
                    mapping_source=MarketplaceStoreMapping.MappingSource.SYNTHETIC_FIXTURE,
                    store_timezone=store.timezone,
                    currency=store.currency,
                )

        jobs = {}
        for row in payload["sync_jobs"]:
            job, _ = SyncJob.objects.update_or_create(
                tenant=tenant,
                integration_config=configs[row["config_id"]],
                resource_type=row["resource_type"],
                defaults={
                    "schedule_type": SyncJob.ScheduleType.MANUAL,
                    "status": SyncJob.Status.IDLE,
                    "is_enabled": True,
                },
            )
            jobs[row["id"]] = job

        runs = {}
        for row in payload["sync_runs"]:
            run = SyncRun.objects.filter(tenant=tenant, run_id=row["run_id"]).first()
            values = {
                "sync_job": jobs[row["job_id"]],
                "idempotency_key": f"handoff:{row['run_id']}",
                "status": row["status"],
                "started_at": parse_datetime(row["started_at"]),
                "finished_at": parse_datetime(row["finished_at"]),
                "fetched_count": row.get("fetched_count", 0),
                "created_count": row.get("created_count", 0),
                "updated_count": row.get("updated_count", 0),
                "skipped_count": row.get("skipped_count", 0),
                "failed_count": row.get("failed_count", 0),
            }
            if run is None:
                run = SyncRun.objects.create(tenant=tenant, run_id=row["run_id"], **values)
            else:
                for field, value in values.items():
                    setattr(run, field, value)
                run.save(update_fields=values.keys())
            runs[row["id"]] = run

        lines_by_order = {}
        for line in payload["sales_order_items"]:
            normalized_line = dict(line)
            normalized_line.setdefault(
                "platform_product_id",
                f"synthetic-product-{line['seller_sku']}",
            )
            lines_by_order.setdefault(line["sales_order_id"], []).append(normalized_line)
        orders = {}
        for row in payload["sales_orders"]:
            normalized = {
                **row,
                "store_id": stores[row["store_id"]].id,
                "contract_version": "shopapi-handoff.v1",
                "lines": lines_by_order.get(row["id"], []),
            }
            orders[row["id"]] = upsert_normalized_order(
                tenant=tenant, payload=normalized, source_run=runs[row["source_run_id"]]
            )

        items_by_refund = {}
        for item in payload["refund_return_items"]:
            items_by_refund.setdefault(item["refund_return_id"], []).append(item)
        order_rows = {row["id"]: row for row in payload["sales_orders"]}
        for row in payload["refund_returns"]:
            run = runs[row["source_run_id"]]
            order_row = order_rows.get(row.get("sales_order_id"))
            normalized = {
                **row,
                "store_id": stores[row["store_id"]].id,
                "external_order_id": order_row["external_order_id"] if order_row else "",
                "requested_at_utc": (run.started_at or run.finished_at).isoformat(),
                "updated_at_utc": (run.finished_at or run.started_at).isoformat(),
                "completed_at_utc": (run.finished_at.isoformat() if row["normalized_status"] == "completed" else None),
                "items": items_by_refund.get(row["id"], []),
            }
            upsert_normalized_refund(tenant=tenant, payload=normalized, source_run=run)

        for row in payload["inventory_snapshots"]:
            normalized = {**row, "warehouse_id": warehouses[row["warehouse_id"]].id}
            upsert_inventory_snapshot(
                tenant=tenant, payload=normalized, source_run=runs[row["source_run_id"]]
            )

        counts = {
            "stores": len(stores),
            "warehouses": len(warehouses),
            "configs": len(configs),
            "jobs": len(jobs),
            "runs": len(runs),
            "orders": len(orders),
            "refunds": len(payload["refund_returns"]),
            "inventory": len(payload["inventory_snapshots"]),
        }
        if not options["commit"]:
            transaction.set_rollback(True)
        mode = "COMMIT" if options["commit"] else "DRY-RUN ROLLBACK"
        self.stdout.write(self.style.SUCCESS(f"{mode}: {json.dumps(counts, ensure_ascii=False, sort_keys=True)}"))
