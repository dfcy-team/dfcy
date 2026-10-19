import json

from django.core.management.base import BaseCommand, CommandError

from apps.influencers.tiktok_dataset_import import DatasetImportError, MAX_ROWS_PER_RUN, run_import


class Command(BaseCommand):
    help = "Read-only dataset eligibility preview; formal import is disabled. No live requests."

    def add_arguments(self, parser):
        for name in ("manifest", "manifest-sha256"):
            parser.add_argument("--" + name, required=True)
        for name in ("tenant-id", "store-id", "actor-id"):
            parser.add_argument("--" + name, required=True, type=int)
        parser.add_argument("--limit", type=int, default=MAX_ROWS_PER_RUN)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["apply"]:
            raise CommandError("formal_import_disabled_use_staging")
        try:
            result = run_import(
                manifest_path=options["manifest"], manifest_sha256=options["manifest_sha256"],
                tenant_id=options["tenant_id"], store_id=options["store_id"], actor_id=options["actor_id"],
                limit=options["limit"], apply=False,
            )
        except DatasetImportError as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError("dataset_preview_failed") from None
        self.stdout.write(json.dumps(result, sort_keys=True))
