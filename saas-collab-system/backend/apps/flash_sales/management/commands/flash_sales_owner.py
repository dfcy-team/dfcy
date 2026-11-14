import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.flash_sales.domain import TERMINAL
from apps.flash_sales.models import ImportMapping, Plan, StoreTask, TenantControl, WriteOperation
from apps.flash_sales.services import audit
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Pause scheduling or record an independently verified, single-owner cutover. Never enables plans."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-code", required=True)
        parser.add_argument("--actor", required=True, help="Current tenant superuser username, not a numeric ID")
        parser.add_argument("--owner", required=True, choices=["paused", "saas", "legacy"])
        parser.add_argument("--evidence")
        parser.add_argument("--sha256")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(code=options["tenant_code"])
            actor = CustomUser.objects.get(tenant=tenant, username=options["actor"], is_active=True, is_superuser=True, user_type="internal")
        except (Tenant.DoesNotExist, CustomUser.DoesNotExist):
            raise CommandError("当前租户及管理员身份校验失败。") from None
        control, _ = TenantControl.objects.get_or_create(tenant=tenant)
        control = TenantControl.objects.select_for_update().get(pk=control.pk)
        owner = options["owner"]
        evidence_hash = ""
        if owner != "paused":
            if control.scheduler_owner != "paused":
                raise CommandError("须先暂停当前执行源。")
            if StoreTask.objects.filter(tenant=tenant).exclude(status__in=TERMINAL).exists() or WriteOperation.objects.filter(tenant=tenant, status="submitted").exists():
                raise CommandError("仍有未完成任务或未知写入；先逐项回读核对，不能切换或盲目回滚。")
            try:
                raw = Path(options["evidence"]).read_bytes()
                evidence_hash = hashlib.sha256(raw).hexdigest()
                evidence = json.loads(raw)
            except (TypeError, OSError, ValueError):
                raise CommandError("缺少独立核对的停止与增量对账证据。") from None
            if evidence_hash != options["sha256"] or evidence.get("tenant_code") != tenant.code or evidence.get("target_owner") != owner:
                raise CommandError("证据摘要、租户或目标执行源不匹配。")
            if not (evidence.get("previous_source_stopped") is True and evidence.get("writes_reconciled") is True and evidence.get("verified_by") and evidence.get("verified_at")):
                raise CommandError("证据缺少原执行源已停止、写入已核对及独立核对人记录。")
            if evidence.get("imported_record_count") != ImportMapping.objects.filter(tenant=tenant).count():
                raise CommandError("最终增量记录数不一致。")
        Plan.objects.filter(tenant=tenant).update(enabled=False)
        control.scheduler_owner = owner
        control.cutover_watermark = timezone.now()
        control.last_dispatch_at = timezone.now() if owner == "saas" else None
        control.version += 1
        control.save()
        audit(actor, "flash_scheduler_owner", control, {"owner": owner, "evidence_sha256": evidence_hash, "plans_paused": True})
        self.stdout.write(json.dumps({"owner": owner, "plans_paused": True, "version": control.version}))
