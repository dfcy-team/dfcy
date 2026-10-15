from decimal import Decimal
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.influencers.models import BdSampleAttributionSnapshot, SampleFulfillment, SampleItem
from apps.influencers.sample_costs import confirmed_sample_cost_for
from apps.influencers.services import _purchase_cost_for_item
from apps.masterdata.models import StatusChoices, WarehouseMaster
from apps.tenants.models import Tenant


def eligible_items(tenant, after_id=0):
    return SampleItem.objects.filter(
        Q(cost_match_status="cost_unmatched", cost_source="product_cost_version_unmatched")
        | Q(cost_match_status="pending", cost_source__in=["", "legacy_shop_analytics_bd"]),
        tenant=tenant, fulfillment__tenant=tenant, fulfillment__is_deleted=False,
        id__gt=after_id, cost_version__isnull=True, unit_cost__isnull=True, cost_amount__isnull=True,
    ).order_by("id")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Command(BaseCommand):
    help = "Preview or fill unmatched sample costs from confirmed SKU/warehouse cost versions."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--after-item-id", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report-path")
        parser.add_argument("--expected-plan")

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

        base = eligible_items(tenant, options["after_item_id"])
        item_ids = list(base.values_list("id", flat=True)[:batch_size + 1])
        has_more = len(item_ids) > batch_size
        item_ids = item_ids[:batch_size]
        cursor = item_ids[-1] if item_ids else options["after_item_id"]
        scanned = len(item_ids)
        counts = {"matched": 0, "applied": 0}
        matched_item_ids = []
        rows = []
        expected = None
        if options.get("expected_plan"):
            expected = json.loads(Path(options["expected_plan"]).read_text())
            if expected["tenant_id"] != tenant.pk or not options["apply"]:
                raise CommandError("An expected plan requires apply mode and the same tenant.")
            expected = {row["item_id"]: row for row in expected["rows"] if row["result"] == "matched"}
            item_ids = [item_id for item_id in item_ids if item_id in expected]
        groups = {}
        for item_id, fulfillment_id in base.filter(pk__in=item_ids).values_list("id", "fulfillment_id"):
            groups.setdefault(fulfillment_id, []).append(item_id)
        for fulfillment_id, selected_ids in groups.items():
            with transaction.atomic():
                parent_query = SampleFulfillment.objects.filter(pk=fulfillment_id, tenant=tenant, is_deleted=False)
                if options["apply"]:
                    parent_query = parent_query.select_for_update()
                parent = parent_query.select_related("store").first()
                if parent is None:
                    continue
                item_query = SampleItem.objects.filter(tenant=tenant, fulfillment=parent).order_by("id")
                snapshot_query = BdSampleAttributionSnapshot.objects.filter(tenant=tenant, fulfillment=parent).order_by("id")
                if options["apply"]:
                    item_query = item_query.select_for_update()
                    snapshot_query = snapshot_query.select_for_update()
                items = list(item_query.select_related("sku", "warehouse"))
                snapshots = list(snapshot_query)
                current_ids = set(base.filter(pk__in=selected_ids).values_list("id", flat=True))
                protected_total = parent.calculated_cost is not None or any(s.cost_amount is not None for s in snapshots)
                currencies = {i.currency for i in items if i.cost_amount is not None}
                planned = []
                for item in items:
                    if item.pk not in current_ids:
                        continue
                    row = {"item_id": item.pk, "fulfillment_id": parent.pk,
                           "sample_no": parent.fulfillment_no, "requested_sku": item.requested_sku,
                           "before_digest": fingerprint({
                               "parent": (parent.pk, parent.store_id, parent.owner_id, parent.influencer_id,
                                          parent.sample_sent_at, parent.shipped_at, parent.status, parent.calculated_cost),
                               "item": (item.pk, item.updated_at, item.quantity, item.sku_id, item.warehouse_id,
                                        item.requested_sku, item.site_code, item.cost_match_status, item.cost_source),
                               "snapshots": [(s.pk, s.cost_amount, s.currency) for s in snapshots],
                           })}
                    proposal, reason = self.resolve(tenant, parent, item, protected_total, currencies)
                    row["result"] = reason
                    if proposal:
                        row.update({"sku_id": proposal["sku"].pk, "warehouse_id": proposal["warehouse"].pk,
                                    "cost_version_id": proposal["version"].pk, "currency": proposal["version"].currency,
                                    "unit_cost": str(proposal["version"].confirmed_cost),
                                    "cost_amount": str(proposal["amount"]), "quantity": item.quantity,
                                    "cost_source": proposal["source"]})
                        if expected is not None and row != expected[item.pk]:
                            raise CommandError("Sample or cost source changed since the reviewed plan; no group changes committed.")
                        currencies.add(proposal["version"].currency)
                        planned.append((item, proposal))
                        counts["matched"] += 1
                        matched_item_ids.append(item.pk)
                    else:
                        if expected is not None:
                            raise CommandError("A reviewed match is no longer valid; recapture the plan.")
                        counts[reason] = counts.get(reason, 0) + 1
                    rows.append(row)
                if not options["apply"] or not planned:
                    continue
                proposed = {item.pk: proposal["amount"] for item, proposal in planned}
                amounts = [proposed.get(item.pk, item.cost_amount) for item in items]
                if all(amount is not None for amount in amounts) and sum(amounts, Decimal("0")) >= Decimal("1e14"):
                    raise CommandError("Sample cost total exceeds supported precision; no group changes committed.")
                now = timezone.now()
                for item, proposal in planned:
                    version, sku, warehouse = proposal["version"], proposal["sku"], proposal["warehouse"]
                    original_status = item.cost_match_status
                    QuerySet.update(
                        SampleItem.objects.filter(pk=item.pk, tenant=tenant), sku=sku, warehouse=warehouse,
                        cost_version=version, normalized_sku=proposal["normalized"], matched_sku_code=sku.sku_code,
                        matched_legacy_sku_code=sku.legacy_sku_code, cost_match_status=proposal["status"],
                        cost_source=proposal["source"], unit_cost=version.confirmed_cost,
                        cost_amount=proposal["amount"], currency=version.currency, cost_snapshot_at=now, updated_at=now,
                    )
                    item.cost_amount, item.currency = proposal["amount"], version.currency
                    write_operation_log(
                        tenant=tenant, user=actor, module="influencers", action="backfill_sample_confirmed_cost",
                        object_type="sample_item", object_id=item.pk,
                        before_data={"cost_match_status": original_status},
                        after_data={"cost_version_id": version.pk, "cost_amount": str(proposal["amount"]),
                                    "cost_source": proposal["source"], "warehouse_id": warehouse.pk},
                    )
                    counts["applied"] += 1
                complete = all(i.cost_amount is not None and i.currency for i in items)
                total = sum((i.cost_amount for i in items), Decimal("0")) if complete else None
                QuerySet.update(
                    SampleFulfillment.objects.filter(pk=parent.pk, tenant=tenant),
                    calculated_cost=total, version=F("version") + 1, updated_at=now,
                )
                if complete:
                    QuerySet.update(snapshot_query, cost_amount=total, currency=next(iter(currencies)), updated_at=now)
        self.result = {"tenant_id": tenant.pk, "scanned": scanned, "next_after_item_id": cursor,
                       "has_more": has_more, "counts": counts, "rows": rows}
        if options.get("report_path"):
            with Path(options["report_path"]).open("x", encoding="utf-8") as stream:
                json.dump(self.result, stream, default=str)
        self.stdout.write(
            f"mode={'apply' if options['apply'] else 'dry-run'} tenant={tenant.pk} "
            f"scanned={scanned} next_after_item_id={cursor} has_more={str(has_more).lower()} "
            + " ".join(f"{key}={value}" for key, value in counts.items())
            + f" matched_item_ids={','.join(str(pk) for pk in matched_item_ids[:20]) or 'none'}"
        )

    def resolve(self, tenant, parent, item, protected_total, currencies):
        if protected_total:
            return None, "existing_total"
        if parent.store.tenant_id != tenant.pk or item.quantity < 1:
            return None, "invalid_source"
        if item.sku_id:
            sku = item.sku if item.sku.tenant_id == tenant.pk and item.sku.is_active else None
            normalized, status = item.normalized_sku, "matched_new_sku"
        else:
            normalized, sku, status = _purchase_cost_for_item(tenant, item.requested_sku)
            if status not in {"matched_new_sku", "matched_legacy_sku"}:
                sku = None
        if sku is None:
            return None, "no_sku"
        country = (parent.store.country_code or "").strip().upper()
        # Historical imports used the exact shop code in site_code, not the country code.
        site_aliases = {"", country, parent.store.code.strip().upper()}
        if not country or item.site_code.strip().upper() not in site_aliases:
            return None, "country_conflict"
        if item.warehouse_id:
            warehouses = [item.warehouse] if (
                item.warehouse.tenant_id == tenant.pk and item.warehouse.status == StatusChoices.ACTIVE
                and item.warehouse.country_code.strip().upper() == country
            ) else []
        else:
            warehouses = list(WarehouseMaster.objects.filter(
                tenant=tenant, status=StatusChoices.ACTIVE, country_code__iexact=country,
            ).order_by("id")[:2])
        if len(warehouses) != 1:
            return None, "warehouse_ambiguous"
        occurred_at = parent.shipped_at or parent.sample_sent_at
        if occurred_at is None:
            return None, "missing_date"
        version, source = confirmed_sample_cost_for(
            tenant=tenant, sku=sku, warehouse=warehouses[0], occurred_at=occurred_at,
        )
        if version is None or version.confirmed_cost is None:
            return None, "no_version"
        if not version.confirmed_cost.is_finite() or version.confirmed_cost < 0 or not version.currency:
            return None, "invalid_cost"
        if currencies and currencies != {version.currency}:
            return None, "currency_conflict"
        amount = version.confirmed_cost * item.quantity
        if amount >= Decimal("1e14"):
            return None, "invalid_cost"
        return {"sku": sku, "warehouse": warehouses[0], "version": version, "source": source,
                "normalized": normalized, "status": status, "amount": amount}, "matched"
