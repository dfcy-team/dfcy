import hashlib
import json
import os
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.services import write_operation_log
from apps.influencers.models import InfluencerNumberReservation, OutreachTask, SampleFulfillment
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.tenants.models import Tenant


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def make_plan(tenant):
    tasks = list(OutreachTask.objects.filter(tenant=tenant).order_by("id").values("id", "task_no", "version"))
    samples = list(SampleFulfillment.objects.filter(tenant=tenant).order_by("id").values(
        "id", "fulfillment_no", "type_no", "link_type", "version", "outreach_task_id", "outreach_target_id",
        "influencer_id", "owner_id", "store_id", "source", "external_id", "calculated_cost", "status", "is_deleted",
    ))
    existing = list(InfluencerNumberReservation.objects.filter(tenant=tenant).order_by("id").values(
        "namespace", "number", "task_id", "sample_id",
    ))
    owners = {}
    additions = []
    maxima = {}

    def remember(namespace, number, owner, *, add=True):
        key = (namespace, number.casefold())
        if key in owners and owners[key] != owner:
            raise CommandError("Conflicting number reservations; no writes are safe.")
        if key not in owners:
            owners[key] = owner
            if add:
                additions.append({"namespace": namespace, "number": number,
                                  "task_id": owner if namespace == "task" else None,
                                  "sample_id": owner if namespace != "task" else None})
            match = re.fullmatch(r"(.*?)(\d+)", number)
            if match:
                counter = (namespace, match[1].casefold())
                maxima[counter] = max(maxima.get(counter, 0), int(match[2]))

    def allocate(namespace, prefix, owner, width=4):
        number = f"{prefix}{maxima.get((namespace, prefix.casefold()), 0) + 1:0{width}d}"
        remember(namespace, number, owner)
        return number

    valid_tasks = {row["id"] for row in tasks}
    valid_samples = {row["id"] for row in samples}
    for row in existing:
        owner = row["task_id"] if row["namespace"] == "task" else row["sample_id"]
        if owner not in (valid_tasks if row["namespace"] == "task" else valid_samples):
            raise CommandError("A reservation references an unrelated tenant or missing owner.")
        remember(row["namespace"], row["number"], owner, add=False)
    for row in tasks:
        remember("task", row["task_no"], row["id"])
    for row in samples:
        remember("sample", row["fulfillment_no"], row["id"])
        if row["type_no"]:
            remember("type", row["type_no"], row["id"])

    proposed_types = {}
    for row in samples:
        if not row["type_no"] and re.fullmatch(re.escape(row["link_type"]) + r"\d+", row["fulfillment_no"], flags=re.IGNORECASE):
            remember("type", row["fulfillment_no"], row["id"])
            proposed_types[row["id"]] = row["fulfillment_no"]

    changes = []
    for row in samples:
        type_no = row["type_no"] or proposed_types.get(row["id"]) or allocate("type", row["link_type"], row["id"])
        number = row["fulfillment_no"]
        if not re.fullmatch(r"YPDD\d+", number, flags=re.IGNORECASE):
            if not any(re.fullmatch(re.escape(kind) + r"\d+", number) for kind, _ in SampleFulfillment.LINK_TYPE_CHOICES):
                raise CommandError("Unexpected non-YPDD number; review it before applying.")
            number = allocate("sample", "YPDD", row["id"], 5)
        if type_no != row["type_no"] or number != row["fulfillment_no"]:
            changes.append({"id": row["id"], "version": row["version"],
                            "before": {"fulfillment_no": row["fulfillment_no"], "type_no": row["type_no"]},
                            "after": {"fulfillment_no": number, "type_no": type_no}})
    plan = {"tenant_id": tenant.pk, "task_count": len(tasks), "sample_count": len(samples),
            "type_counts": dict(Counter(row["link_type"] for row in samples)),
            "source_digest": digest({"tasks": tasks, "samples": samples, "reservations": existing}),
            "changes": changes, "reservations": additions}
    plan["digest"] = digest(plan)
    return plan


class Command(BaseCommand):
    help = "Preview or backfill independent sample type numbers, preserving YPDD and relationship IDs."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-plan")
        parser.add_argument("--report-path")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        actor = get_user_model().objects.filter(pk=options["actor_id"], tenant=tenant, is_active=True).first()
        if not tenant or not actor or actor.user_type != actor.UserType.INTERNAL:
            raise CommandError("An active tenant and internal actor are required.")
        for permission in ("influencers.outreach.manage", "influencers.fulfillment.manage"):
            if not check_user_permission(actor, permission):
                raise CommandError("The actor lacks number-management permissions.")
            require_all_scope(actor, permission)
        if options["apply"] and not (options["expected_plan"] and options["report_path"]):
            raise CommandError("Apply requires an expected preview and an exclusive report file.")
        expected = json.loads(Path(options["expected_plan"]).read_text()) if options["expected_plan"] else None
        with ExitStack() as stack:
            report = None
            if options["report_path"]:
                try:
                    descriptor = os.open(options["report_path"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    report = stack.enter_context(os.fdopen(descriptor, "w", encoding="utf-8"))
                except OSError as exc:
                    raise CommandError("Cannot create report; no number changes were made.") from exc
            with transaction.atomic():
                if options["apply"]:
                    Tenant.objects.select_for_update().get(pk=tenant.pk)
                plan = make_plan(tenant)
                if expected is not None and expected.get("digest") != plan["digest"]:
                    raise CommandError("The source changed since preview; no changes committed.")
                if options["apply"]:
                    # The reviewed plan validates every owner against this tenant.
                    # Keep the general influencer bulk-write guard enabled.
                    QuerySet.bulk_create(InfluencerNumberReservation.objects.filter(tenant=tenant), [
                        InfluencerNumberReservation(tenant=tenant, **row) for row in plan["reservations"]
                    ], batch_size=500)
                    now = timezone.now()
                    for row in plan["changes"]:
                        updated = QuerySet.update(SampleFulfillment.objects.filter(
                            tenant=tenant, pk=row["id"], version=row["version"], **row["before"],
                        ), **row["after"], version=row["version"] + 1, updated_at=now)
                        if updated != 1:
                            raise CommandError("A sample changed during apply; all changes rolled back.")
                    if plan["changes"] or plan["reservations"]:
                        write_operation_log(
                            tenant=tenant, user=actor, module="influencers", action="backfill_sample_business_numbers",
                            object_type="tenant", object_id=tenant.pk,
                            after_data={"plan_digest": plan["digest"], "samples_changed": len(plan["changes"]),
                                        "reservations_created": len(plan["reservations"]), "relationship_changes": 0},
                        )
                summary = {"applied": options["apply"], "digest": plan["digest"],
                           "sample_count": plan["sample_count"], "type_counts": plan["type_counts"],
                           "samples_changed": len(plan["changes"]),
                           "YPDD_renames": sum(row["before"]["fulfillment_no"] != row["after"]["fulfillment_no"] for row in plan["changes"]),
                           "reservations_created": len(plan["reservations"]), "relationship_changes": 0,
                           "deletes": 0}
                if report is not None:
                    try:
                        json.dump({**plan, "summary": summary}, report)
                        report.flush()
                        os.fsync(report.fileno())
                        report.close()
                    except OSError as exc:
                        raise CommandError("Cannot finish report; all database changes rolled back.") from exc
        self.result = plan
        self.stdout.write(json.dumps(summary))
