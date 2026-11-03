import json

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import CustomUser
from apps.sales_management.order_field_backfill import build_plan, apply_plan


class Command(BaseCommand):
    help = 'Preview or apply existing-order field enrichment from local RAW; never call providers.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expected-plan-sha256', default='')

    def handle(self, *args, **options):
        actor = CustomUser.objects.filter(username=options['actor'], is_active=True).first()
        if actor is None or not actor.is_superuser:
            raise CommandError('离线历史回填仅允许明确指定的活动超级管理员执行。')
        plan, summary = build_plan(actor)
        if options['apply']:
            if not options['expected_plan_sha256'] or options['expected_plan_sha256'] != summary['plan_sha256']:
                raise CommandError('回填计划与已确认预览不一致；本次未写入。')
            summary['applied'] = apply_plan(actor, plan)
        else:
            summary['dry_run'] = True
        self.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))
