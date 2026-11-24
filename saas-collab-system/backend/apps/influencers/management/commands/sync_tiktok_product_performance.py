"""Fetch TikTok product funnel metrics; writes only with --apply."""
import json
from datetime import date
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.influencers.tiktok_product_sync import run_window, DatasetError


class Command(BaseCommand):
    help = 'Fetch a completed 1..31 day TikTok product metrics window (dry-run by default).'

    def add_arguments(self,parser):
        parser.add_argument('--actor-id',type=int,required=True);parser.add_argument('--tenant-id',type=int,required=True)
        parser.add_argument('--store-id',type=int,required=True);parser.add_argument('--start-date',required=True)
        parser.add_argument('--end-date',required=True,help='Exclusive shop-local end date')
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**o):
        actor=get_user_model().objects.get(pk=o['actor_id'])
        if not actor.is_active or actor.tenant_id!=o['tenant_id']: raise CommandError('Invalid actor/tenant.')
        try: result=run_window(actor,o['store_id'],date.fromisoformat(o['start_date']),date.fromisoformat(o['end_date']),apply=o['apply'])
        except Exception as exc:
            reason=str(exc) if isinstance(exc,DatasetError) else type(exc).__name__
            raise CommandError(reason) from None
        self.stdout.write(json.dumps(result))
