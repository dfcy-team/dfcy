import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from apps.influencers.video_registered_reconcile import reconcile


class Command(BaseCommand):
    help='Reconcile API videos with exact registered video/store identities, never nickname-only.'

    def add_arguments(self,parser):
        parser.add_argument('--actor-id',type=int,required=True)
        parser.add_argument('--tenant-id',type=int,required=True)
        parser.add_argument('--store-id',type=int,required=True)
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        actor=get_user_model().objects.get(pk=options['actor_id'])
        if actor.tenant_id!=options['tenant_id']:raise CommandError('Tenant mismatch.')
        self.stdout.write(json.dumps(reconcile(actor,options['store_id'],apply=options['apply'])))
