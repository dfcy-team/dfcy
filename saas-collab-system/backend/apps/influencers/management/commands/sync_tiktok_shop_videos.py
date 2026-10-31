"""Dedicated video worker; never dispatches other resource types."""
from datetime import date, timedelta
import json
import time
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.integrations.models import MarketplaceStoreAuthorization
from apps.influencers.tiktok_video_sync import run_day, DatasetError


class Command(BaseCommand):
    help = 'Sync complete shop-local days to video tables only; no fulfillment changes.'

    def add_arguments(self, parser):
        parser.add_argument('--actor-id',type=int,required=True)
        parser.add_argument('--tenant-id',type=int,required=True)
        scope=parser.add_mutually_exclusive_group(required=True)
        scope.add_argument('--store-id',type=int)
        scope.add_argument('--all-authorized',action='store_true')
        period=parser.add_mutually_exclusive_group(required=True)
        period.add_argument('--date')
        period.add_argument('--days',type=int)
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--refresh',action='store_true')
        parser.add_argument('--pause',type=float,default=2)

    def handle(self,*args,**options):
        actor=get_user_model().objects.get(pk=options['actor_id'])
        if not actor.is_active or actor.tenant_id!=options['tenant_id'] or not 0<=options['pause']<=60:
            raise CommandError('Invalid actor/pause.')
        if options['days'] is not None and not 1<=options['days']<=30:
            raise CommandError('days must be 1..30.')
        if options['all_authorized']:
            ids=list(MarketplaceStoreAuthorization.objects.filter(tenant_id=actor.tenant_id,
                platform='tiktok',status='active',expires_at__gt=timezone.now()).order_by('store_id')
                .values_list('store_id',flat=True).distinct())
        else:
            ids=[options['store_id']]
        results=[]
        for store_id in ids:
            try:
                from apps.influencers.tiktok_video_sync import resolve
                auth=resolve(actor,store_id)
                today=timezone.now().astimezone(ZoneInfo(auth.store.timezone)).date()
                days=[date.fromisoformat(options['date'])] if options['date'] else [today-timedelta(days=n) for n in range(1,options['days']+1)]
            except Exception as exc:
                r={'store_id':store_id,'status':'blocked','reason':str(exc) if isinstance(exc,DatasetError) else type(exc).__name__}
                results.append(r);self.stdout.write(json.dumps(r));self.stdout.flush();continue
            for day in days:
                try:
                    r=run_day(actor,store_id,day,apply=options['apply'],refresh=options['refresh'])
                except Exception as exc:
                    r={'store_id':store_id,'date':str(day),'status':'failed',
                       'reason':str(exc) if isinstance(exc,DatasetError) else type(exc).__name__}
                results.append(r);self.stdout.write(json.dumps(r));self.stdout.flush()
                if r['status']=='failed':
                    # Stop this shop on error; do not turn one permission failure into 30 retries.
                    break
                time.sleep(options['pause'])
        summary={s:sum(r['status']==s for r in results) for s in ['completed','already_completed','dry_run','failed','blocked']}
        self.stdout.write(json.dumps({'summary':summary,'stores':len(ids)}))
        if summary['failed'] or summary['blocked']:
            raise CommandError('Video worker finished with failed/blocked shops; see sanitized results.')
