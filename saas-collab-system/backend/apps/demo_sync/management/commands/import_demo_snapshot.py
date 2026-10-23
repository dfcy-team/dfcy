import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate/import an extracted snapshot into an isolated disposable Demo database."

    def add_arguments(self, parser):
        parser.add_argument("bundle", type=Path)
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--confirm-disposable-demo", action="store_true")

    def handle(self, *args, **options):
        if options["commit"] and not options["confirm_disposable_demo"]:
            raise CommandError("COMMIT_REQUIRES_DISPOSABLE_DEMO_CONFIRMATION")
        from apps.demo_sync.importer import import_snapshot
        try:
            summary = import_snapshot(options["bundle"], tenant_id=options["tenant_id"],
                                      actor_id=options["actor_id"], dry_run=not options["commit"])
        except Exception as error:
            code = getattr(error, "code", "DEMO_IMPORT_REJECTED")
            raise CommandError(code if isinstance(code, str) else "DEMO_IMPORT_REJECTED") from None
        self.stdout.write(json.dumps(summary, ensure_ascii=False, default=str))
