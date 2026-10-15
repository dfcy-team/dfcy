from contextlib import ExitStack
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.influencers.models import BdSampleAttributionSnapshot, SampleFulfillment, SampleItem
from apps.influencers.sample_costs import COST_FIELDS, sample_cost_total
from apps.influencers.services import _current_sample_item_costs
from apps.products.models import ProductCostVersion
from apps.tenants.models import Tenant


POLICY = "current_confirmed_sample_cost_v1"


def canonical(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True).encode()).hexdigest()


class Command(BaseCommand):
    help = "Preview all sample costs against the current confirmed ledger; apply requires an unchanged plan."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", required=True, type=int)
        parser.add_argument("--actor-id", required=True, type=int)
        parser.add_argument("--after-fulfillment-id", default=0, type=int)
        parser.add_argument("--batch-size", default=100, type=int)
        parser.add_argument("--report-path")
        parser.add_argument("--expected-plan")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        self.result = None
        size, cursor = options["batch_size"], options["after_fulfillment_id"]
        if not 1 <= size <= 100 or cursor < 0:
            raise CommandError("Batch size must be 1..100; cursor must be non-negative.")
        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        user = CustomUser.objects.filter(
            tenant=tenant, pk=options["actor_id"], is_active=True,
            user_type=CustomUser.UserType.INTERNAL, is_superuser=True,
        ).first() if tenant else None
        if user is None:
            raise CommandError("An active internal tenant superuser is required for historical repricing.")
        expected = None
        if options["apply"] != bool(options.get("expected_plan")):
            raise CommandError("Apply requires --expected-plan; preview must not use it.")
        if options.get("expected_plan"):
            try:
                expected = json.loads(Path(options["expected_plan"]).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise CommandError("Cannot read the reviewed plan.") from exc
        with ExitStack() as stack:
            report = None
            if options.get("report_path"):
                try:
                    descriptor = os.open(options["report_path"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    try:
                        stream = os.fdopen(descriptor, "w", encoding="utf-8")
                    except BaseException:
                        os.close(descriptor)
                        raise
                    report = stack.enter_context(stream)
                except OSError as exc:
                    raise CommandError("Cannot create report file; no sample costs were changed.") from exc
            with transaction.atomic():
                # Match the business service lock order and keep each sample whole.
                if options["apply"]:
                    Tenant.objects.select_for_update().get(pk=tenant.pk)
                parents = SampleFulfillment.objects.filter(
                    tenant=tenant, is_deleted=False, pk__gt=cursor,
                ).order_by("pk")
                ids = list(parents.values_list("pk", flat=True)[:size + 1])
                has_more, selected_ids = len(ids) > size, ids[:size]
                selected = parents.filter(pk__in=selected_ids)
                if options["apply"]:
                    selected = selected.select_for_update()
                plans = []
                pricing_time = timezone.now()
                for parent in selected.select_related("store"):
                    items_query = SampleItem.objects.filter(tenant=tenant, fulfillment=parent).order_by("pk")
                    snapshots_query = BdSampleAttributionSnapshot.objects.filter(tenant=tenant, fulfillment=parent).order_by("pk")
                    if parent.items.exclude(tenant=tenant).exists():
                        raise CommandError("Cross-tenant child data requires separate review.")
                    if options["apply"]:
                        items_query, snapshots_query = items_query.select_for_update(), snapshots_query.select_for_update()
                    items = list(items_query.select_related("sku", "warehouse"))
                    snapshots = list(snapshots_query)
                    changes, proposed = [], []
                    for item in items:
                        fields = _current_sample_item_costs(
                            tenant=tenant, fulfillment=parent, as_of=pricing_time, allow_auto_warehouse=True, strict_sku=False,
                            payload={"sku": item.sku, "warehouse": item.warehouse,
                                     "requested_sku": item.requested_sku, "site_code": item.site_code,
                                     "quantity": item.quantity},
                        )
                        before = {field: getattr(item, field) for field in COST_FIELDS}
                        proposed.append(SimpleNamespace(**fields))
                        changes.append({"item_id": item.pk, "before": canonical(before), "after": canonical(fields)})
                    total, currency = sample_cost_total(proposed)
                    version_ids = {item.cost_version_id for item in proposed if item.cost_version_id is not None}
                    plan = {
                        "fulfillment_id": parent.pk, "sample_no": parent.fulfillment_no,
                        "before_digest": digest({
                            "parent": SampleFulfillment.objects.filter(pk=parent.pk, tenant=tenant).values().get(),
                            "items": list(items_query.values()), "snapshots": list(snapshots_query.values()),
                        }),
                        "cost_basis_digest": digest(list(ProductCostVersion.objects.filter(
                            tenant=tenant, pk__in=version_ids,
                        ).order_by("pk").values())),
                        "items": changes, "total_before": canonical(parent.calculated_cost),
                        "total_after": canonical(total), "currency_after": currency,
                        "snapshot_before": [{"id": s.pk, "amount": canonical(s.cost_amount), "currency": s.currency} for s in snapshots],
                        "unmatched_items": sum(item.cost_amount is None for item in proposed),
                    }
                    plan["changed"] = (
                        any(row["before"] != row["after"] for row in changes)
                        or parent.calculated_cost != total
                        or any((s.cost_amount, s.currency) != (total, currency) for s in snapshots)
                    )
                    plans.append((parent, items, snapshots, plan))
                result = {
                    "policy": POLICY, "tenant_id": tenant.pk, "actor_id": user.pk,
                    "after_fulfillment_id": cursor, "batch_size": size,
                    "next_after_fulfillment_id": selected_ids[-1] if selected_ids else cursor,
                    "has_more": has_more, "rows": [entry[3] for entry in plans],
                }
                if options["apply"] and canonical(result) != expected:
                    raise CommandError("Sample or cost data changed since preview; no writes committed. Generate a new plan.")
                for parent, items, snapshots, plan in plans:
                    if not options["apply"] or not plan["changed"]:
                        continue
                    now = timezone.now()
                    for row in plan["items"]:
                        if row["before"] == row["after"]:
                            continue
                        fields = dict(row["after"])
                        for key in ("unit_cost", "cost_amount"):
                            fields[key] = Decimal(fields[key]) if fields[key] is not None else None
                        QuerySet.update(
                            SampleItem.objects.filter(tenant=tenant, fulfillment=parent, pk=row["item_id"]),
                            **fields, cost_snapshot_at=now, updated_at=now,
                        )
                        write_operation_log(
                            tenant=tenant, user=user, module="influencers", action="reprice_sample_item_confirmed_cost",
                            object_type="sample_item", object_id=row["item_id"],
                            before_data=row["before"], after_data={"policy": POLICY, **row["after"]},
                        )
                    total = Decimal(plan["total_after"]) if plan["total_after"] is not None else None
                    QuerySet.update(
                        SampleFulfillment.objects.filter(tenant=tenant, pk=parent.pk),
                        calculated_cost=total, version=F("version") + 1, updated_at=now,
                    )
                    for snapshot in snapshots:
                        if (snapshot.cost_amount, snapshot.currency) != (total, plan["currency_after"]):
                            QuerySet.update(
                                BdSampleAttributionSnapshot.objects.filter(tenant=tenant, pk=snapshot.pk),
                                cost_amount=total, currency=plan["currency_after"], updated_at=now,
                            )
                    write_operation_log(
                        tenant=tenant, user=user, module="influencers", action="reprice_sample_confirmed_cost",
                        object_type="sample_fulfillment", object_id=parent.pk,
                        before_data={"calculated_cost": plan["total_before"], "snapshots": plan["snapshot_before"]},
                        after_data={"policy": POLICY, "item_count": len(plan["items"]), "plan_digest": digest(plan),
                                    "calculated_cost": plan["total_after"], "currency": plan["currency_after"]},
                    )
                if report:
                    try:
                        json.dump(result, report, ensure_ascii=True)
                        report.flush()
                        os.fsync(report.fileno())
                        stack.close()
                    except OSError as exc:
                        raise CommandError("Cannot finish report file; this batch was rolled back.") from exc
                self.result = result
        self.stdout.write(
            f"mode={'apply' if options['apply'] else 'dry-run'} scanned={len(plans)} "
            f"changed={sum(entry[3]['changed'] for entry in plans)} "
            f"unmatched_items={sum(entry[3]['unmatched_items'] for entry in plans)} "
            f"next_after_fulfillment_id={result['next_after_fulfillment_id']} has_more={str(has_more).lower()}"
        )
