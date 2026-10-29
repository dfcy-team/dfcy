"""Report-only by default; explicit private backup package, never deletion."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from apps.reports.models import ReportExportRequest
from apps.reports.export_backup import build_package


class Command(BaseCommand):
    help = "盘点报表文件存储；仅显式write-package生成本地配对备份文件，不删除对象。"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--write-package", metavar="NEW_DIRECTORY")

    def handle(self, *args, **options):
        records = ReportExportRequest.objects.filter(tenant_id=options["tenant_id"]).order_by("pk")
        if not options["write_package"]:
            self.stdout.write(json.dumps({"read_only": True, "files_deleted": 0,
                "groups": list(records.values("storage_alias").annotate(records=Count("pk")))}))
            return
        try:
            manifest = build_package(records.iterator(chunk_size=100), options["write_package"])
        except Exception:
            raise CommandError("报表备份未完成，请保留部分文件并核对源数据；未删除源文件。") from None
        self.stdout.write(json.dumps({"complete": True, "exports": len(manifest["exports"]),
            "requires_paired_database_snapshot": True, "files_deleted": 0}))
