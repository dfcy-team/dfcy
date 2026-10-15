import json
from django.core.management.base import BaseCommand
from apps.supply_chain.notifications import dispatch_due


class Command(BaseCommand):
    help = 'Process source-bound supply notifications; --dry-run is read-only and never sends.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 100:
            from django.core.management.base import CommandError
            raise CommandError('--limit must be 1–100')
        self.stdout.write(json.dumps(dispatch_due(limit=options['limit'], dry_run=options['dry_run']), ensure_ascii=False))
