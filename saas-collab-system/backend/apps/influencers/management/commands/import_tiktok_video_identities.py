import json

from django.core.management.base import BaseCommand, CommandError

from apps.influencers.tiktok_dataset_import import DatasetImportError, MAX_ROWS_PER_RUN, run_import


class Command(BaseCommand):
    help = "Import observed video identities only; PARTIAL coverage never writes metrics or attribution."

    def add_arguments(self, parser):
        for name in ("manifest", "manifest-sha256"):
            parser.add_argument("--" + name, required=True)
        for name in ("tenant-id", "store-id", "actor-id"):
            parser.add_argument("--" + name, required=True, type=int)
        parser.add_argument("--limit", type=int, default=MAX_ROWS_PER_RUN)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = run_import(
                manifest_path=options["manifest"], manifest_sha256=options["manifest_sha256"],
                tenant_id=options["tenant_id"], store_id=options["store_id"], actor_id=options["actor_id"],
                limit=options["limit"], apply=options["apply"],
            )
        except DatasetImportError as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError("video_identity_import_failed") from None
        self.stdout.write(json.dumps(result, sort_keys=True))
