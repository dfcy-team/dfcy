from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.influencers.models import SampleFulfillment, SampleItem
from apps.influencers.sample_costs import confirmed_sample_cost_for
from apps.influencers.services import _purchase_cost_for_item
from apps.masterdata.models import StatusChoices, WarehouseMaster
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Preview or fill unmatched sample costs from confirmed SKU/warehouse cost versions."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--after-item-id", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        actor = CustomUser.objects.filter(
            pk=options["actor_id"], tenant=tenant, is_active=True,
            user_type=CustomUser.UserType.INTERNAL,
        ).first() if tenant else None
        if actor is None:
            raise CommandError("Tenant and active internal actor must exist.")
        batch_size = options["batch_size"]
        if not 1 <= batch_size <= 500 or options["after_item_id"] < 0:
            raise CommandError("Batch size must be 1..500 and cursor must be non-negative.")

        base = SampleItem.objects.filter(
            tenant=tenant,
            id__gt=options["after_item_id"],
            fulfillment__is_deleted=False,
            cost_match_status="cost_unmatched",
            cost_source="product_cost_version_unmatched",
            cost_version__isnull=True,
            unit_cost__isnull=True,
            cost_amount__isnull=True,
        ).order_by("id")
        item_ids = list(base.values_list("id", flat=True)[:batch_size + 1])
        has_more = len(item_ids) > batch_size
        item_ids = item_ids[:batch_size]
        counts = {"matched": 0, "applied": 0, "no_sku": 0, "warehouse_ambiguous": 0,
                  "no_version": 0, "currency_conflict": 0}
        matched_item_ids = []
        for item_id in item_ids:
            with transaction.atomic():
                item = base.filter(pk=item_id).select_related("fulfillment__store", "sku", "warehouse").first()
                if item is None:
                    continue
                if options["apply"]:
                    item = base.filter(pk=item_id).select_for_update().select_related(
                        "fulfillment__store", "sku", "warehouse",
                    ).first()
                    if item is None:
                        continue
                    SampleFulfillment.objects.select_for_update().get(
                        pk=item.fulfillment_id, tenant=tenant,
                    )
                sku = item.sku if item.sku_id and item.sku.is_active else None
                normalized = item.normalized_sku
                status = "matched_new_sku"
                if sku is None:
                    normalized, sku, status = _purchase_cost_for_item(tenant, item.requested_sku)
                if sku is None:
                    counts["no_sku"] += 1
                    continue
                country = (item.fulfillment.store.country_code or "").strip().upper()
                if item.warehouse_id:
                    warehouses = [item.warehouse] if (
                        item.warehouse.status == StatusChoices.ACTIVE
                        and item.warehouse.country_code.strip().upper() == country
                    ) else []
                else:
                    warehouses = list(WarehouseMaster.objects.filter(
                        tenant=tenant, status=StatusChoices.ACTIVE,
                        country_code__iexact=country,
                    ).order_by("id")[:2])
                if len(warehouses) != 1:
                    counts["warehouse_ambiguous"] += 1
                    continue
                occurred_at = item.fulfillment.shipped_at or item.fulfillment.sample_sent_at
                version, source = confirmed_sample_cost_for(
                    tenant=tenant, sku=sku, warehouse=warehouses[0], occurred_at=occurred_at,
                )
                if version is None:
                    counts["no_version"] += 1
                    continue
                other_currencies = set(SampleItem.objects.filter(
                    tenant=tenant, fulfillment_id=item.fulfillment_id,
                    cost_amount__isnull=False,
                ).exclude(pk=item.pk).values_list("currency", flat=True))
                if other_currencies and other_currencies != {version.currency}:
                    counts["currency_conflict"] += 1
                    continue
                counts["matched"] += 1
                if len(matched_item_ids) < 20:
                    matched_item_ids.append(item.pk)
                if not options["apply"]:
                    continue
                amount = version.confirmed_cost * item.quantity
                now = timezone.now()
                QuerySet.update(
                    SampleItem.objects.filter(pk=item.pk, tenant=tenant),
                    sku=sku, warehouse=warehouses[0], cost_version=version,
                    normalized_sku=normalized, matched_sku_code=sku.sku_code,
                    matched_legacy_sku_code=sku.legacy_sku_code,
                    cost_match_status=status, cost_source=source,
                    unit_cost=version.confirmed_cost, cost_amount=amount,
                    currency=version.currency, cost_snapshot_at=now, updated_at=now,
                )
                amounts = SampleItem.objects.filter(
                    tenant=tenant, fulfillment_id=item.fulfillment_id,
                    cost_amount__isnull=False,
                ).values_list("cost_amount", flat=True)
                QuerySet.update(
                    SampleFulfillment.objects.filter(pk=item.fulfillment_id, tenant=tenant),
                    calculated_cost=sum(amounts, Decimal("0")), updated_at=now,
                )
                write_operation_log(
                    tenant=tenant, user=actor, module="influencers",
                    action="backfill_sample_confirmed_cost", object_type="sample_item",
                    object_id=item.pk,
                    before_data={"cost_match_status": "cost_unmatched"},
                    after_data={"cost_version_id": version.pk, "cost_amount": str(amount),
                                "cost_source": source, "warehouse_id": warehouses[0].pk},
                )
                counts["applied"] += 1
        cursor = item_ids[-1] if item_ids else options["after_item_id"]
        self.stdout.write(
            f"mode={'apply' if options['apply'] else 'dry-run'} tenant={tenant.pk} "
            f"scanned={len(item_ids)} next_after_item_id={cursor} has_more={str(has_more).lower()} "
            + " ".join(f"{key}={value}" for key, value in counts.items())
            + f" matched_item_ids={','.join(str(pk) for pk in matched_item_ids) or 'none'}"
        )
