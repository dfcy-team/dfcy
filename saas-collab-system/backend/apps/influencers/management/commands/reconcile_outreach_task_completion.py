from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import CustomUser
from apps.influencers.models import (
    OutreachTask,
    SampleFulfillment,
    influencer_identity_key,
)
from apps.influencers.services import recompute_outreach_task_completion
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Preview or apply completion of active outreach tasks from sampled creators."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--after-task-id", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        if tenant is None:
            raise CommandError("Tenant does not exist.")
        actor = CustomUser.objects.filter(
            pk=options["actor_id"],
            tenant=tenant,
            is_active=True,
            user_type=CustomUser.UserType.INTERNAL,
        ).first()
        if actor is None:
            raise CommandError("Actor must be an active internal user in the tenant.")

        batch_size = options["batch_size"]
        if batch_size < 1 or batch_size > 500:
            raise CommandError("Batch size must be between 1 and 500.")
        task_rows = list(OutreachTask.objects.filter(
            tenant=tenant,
            is_deleted=False,
            status__in=(OutreachTask.Status.PENDING, OutreachTask.Status.IN_PROGRESS),
            target_count__gt=0,
            id__gt=options["after_task_id"],
        ).order_by("id").values_list("id", "target_count")[:batch_size + 1])
        has_more = len(task_rows) > batch_size
        task_rows = task_rows[:batch_size]
        task_targets = dict(task_rows)
        eligible_ids = []
        current_task_id = None
        sampled_identities = set()
        for task_id, influencer_id, platform, handle in SampleFulfillment.objects.filter(
            tenant=tenant,
            outreach_task_id__in=task_targets,
            is_deleted=False,
        ).values_list(
            "outreach_task_id",
            "influencer_id",
            "influencer__platform",
            "influencer__handle",
        ).order_by("outreach_task_id", "id").iterator(chunk_size=1000):
            if current_task_id is not None and task_id != current_task_id:
                if len(sampled_identities) >= task_targets[current_task_id]:
                    eligible_ids.append(current_task_id)
                sampled_identities = set()
            current_task_id = task_id
            sampled_identities.add(influencer_identity_key(
                influencer_id=influencer_id,
                platform=platform,
                handle=handle,
            ))
        if current_task_id is not None and len(sampled_identities) >= task_targets[current_task_id]:
            eligible_ids.append(current_task_id)

        applied = 0
        if options["apply"]:
            for task_id in eligible_ids:
                task = recompute_outreach_task_completion(user=actor, task=task_id)
                applied += int(task.status == OutreachTask.Status.COMPLETED)

        mode = "apply" if options["apply"] else "dry-run"
        preview = ",".join(str(task_id) for task_id in eligible_ids) or "none"
        next_after_task_id = task_rows[-1][0] if task_rows else options["after_task_id"]
        self.stdout.write(
            self.style.SUCCESS(
                f"mode={mode} tenant={tenant.pk} eligible={len(eligible_ids)} "
                f"applied={applied} eligible_task_ids={preview} "
                f"has_more={str(has_more).lower()} next_after_task_id={next_after_task_id}"
            )
        )
