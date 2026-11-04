import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.integrations.gmv_max_relationship import probe_relationship
from apps.integrations.gmv_max_schedule import safe_error_code
from apps.integrations.models import TikTokAdsAdvertiserMapping


class Command(BaseCommand):
    help = 'Read official Store/advertiser IDs; append observations without changing bindings or amounts.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=int, required=True)
        parser.add_argument('--actor-id', type=int, required=True)
        parser.add_argument('--mapping-id', type=int, action='append')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        actor = get_user_model().objects.get(pk=options['actor_id'])
        if actor.tenant_id != options['tenant_id'] or not actor.is_active:
            raise CommandError('Actor/tenant mismatch.')
        query = TikTokAdsAdvertiserMapping.objects.filter(tenant_id=actor.tenant_id, enabled=True)
        if options.get('mapping_id'):
            query = query.filter(pk__in=options['mapping_id'])
        counts = {'current_verified': 0, 'not_current': 0, 'unverified': 0}
        for mid in query.order_by('pk').values_list('pk', flat=True):
            try:
                result = probe_relationship(actor=actor, mapping_id=mid, commit=options['commit'])
                counts[result['relationship_status']] += 1
                self.stdout.write(json.dumps(result))
            except Exception as exc:
                counts['unverified'] += 1
                self.stdout.write(json.dumps({'mapping_id': mid, 'relationship_status': 'unverified',
                    'error_type': type(exc).__name__, 'error_code': safe_error_code(exc)}))
        self.stdout.write(json.dumps({'summary': counts, 'commit': options['commit']}))
