import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.integrations.sync_run_maintenance import archive_invalid_runs, preview_invalid_runs


class Command(BaseCommand):
    help = "预览/可恢复归档已结束却仍排队的空记录；不删除历史、失败、成功、运行或续跑记录。"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--before", help="固定的带时区截止时间；默认24小时前，apply时必须显式填写")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-plan-sha256")

    def handle(self, *args, **options):
        cutoff = parse_datetime(options["before"]) if options["before"] else timezone.now() - timedelta(hours=24)
        if cutoff is None or timezone.is_naive(cutoff):
            raise CommandError("before必须是带时区的ISO8601时间。")
        if options["apply"] and (not options["before"] or not options["expected_plan_sha256"]):
            raise CommandError("apply必须指定同一预览的before与expected-plan-sha256。")
        try:
            result = (archive_invalid_runs(options["tenant_id"], cutoff, options["expected_plan_sha256"])
                      if options["apply"] else preview_invalid_runs(options["tenant_id"], cutoff))
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        output = {key: value for key, value in result.items() if key != "plan"}
        output.update(tenant_id=options["tenant_id"], cutoff=cutoff.isoformat(),
                      candidate_sample=result["plan"]["candidates"][:20])
        self.stdout.write(json.dumps(output, ensure_ascii=False))
