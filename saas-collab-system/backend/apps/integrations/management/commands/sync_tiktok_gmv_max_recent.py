import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.integrations.ads_subject import mapping_allowed
from apps.integrations.ads_sync import validate_mapping
from apps.integrations.gmv_max_schedule import collect_days, complete_days, safe_error_code
from apps.integrations.gmv_max_sync import run_day, shop_authorization
from apps.integrations.models import TikTokAdsAdvertiserMapping
from apps.permissions.services import user_has_integration_permission


class Command(BaseCommand):
    help = 'Refresh seven complete local GMV Max days for enabled, verified tenant mappings.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=int, required=True)
        parser.add_argument('--actor-id', type=int, required=True)
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, **options):
        actor = get_user_model().objects.get(pk=options['actor_id'])
        if (not actor.is_active or actor.tenant_id != options['tenant_id']
                or not user_has_integration_permission(actor, 'integrations.store.authorize')):
            raise CommandError('Actor is not authorized for this tenant.')
        now = timezone.now()
        totals = {'success': 0, 'failed': 0, 'blocked_accounts': 0, 'planned_days': 0}
        mappings = TikTokAdsAdvertiserMapping.objects.filter(
            tenant_id=options['tenant_id'], enabled=True).select_related(
                'store__platform', 'integration_config', 'tenant').order_by('pk')
        for mapping in mappings.iterator():
            def emit(record):
                self.stdout.write(json.dumps({'mapping_id': mapping.pk,
                    'store_id': mapping.store_id, 'advertiser_id': mapping.advertiser_id,
                    **record}, ensure_ascii=False))
            try:
                if not mapping_allowed(actor, mapping, 'integrations.store.authorize'):
                    raise PermissionError('Mapping is outside actor scope.')
                validate_mapping(mapping)
                shop_authorization(mapping)
                days = complete_days(now, mapping.timezone)
            except Exception as exc:
                totals['blocked_accounts'] += 1
                emit({'status': 'blocked', 'error_type': type(exc).__name__,
                      'error_code': safe_error_code(exc)})
                continue
            totals['planned_days'] += len(days)
            if not options['commit']:
                emit({'status': 'planned_not_collected',
                      'dates': [day.isoformat() for day in days]})
                continue
            counts = collect_days(days, lambda day: run_day(
                actor=actor, mapping_id=mapping.pk, day=day, commit=True), emit)
            for key in counts:
                totals[key] += counts[key]
        self.stdout.write(json.dumps({'summary': totals, 'commit': options['commit']}))
        if totals['failed'] or totals['blocked_accounts']:
            raise CommandError('GMV Max refresh incomplete; see sanitized account/day results.')
