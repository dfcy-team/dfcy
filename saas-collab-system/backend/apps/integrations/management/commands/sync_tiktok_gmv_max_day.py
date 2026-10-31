import json
from datetime import date
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from apps.integrations.gmv_max_sync import run_day


class Command(BaseCommand):
    help = 'Collect one verified GMV Max campaign day into isolated advertising RAW evidence.'

    def add_arguments(self, parser):
        parser.add_argument('--actor-id', type=int, required=True)
        parser.add_argument('--mapping-id', type=int, required=True)
        parser.add_argument('--date', required=True)
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        result = run_day(actor=get_user_model().objects.get(pk=options['actor_id']),
            mapping_id=options['mapping_id'],day=date.fromisoformat(options['date']),commit=options['commit'])
        self.stdout.write(json.dumps(result,ensure_ascii=False))
