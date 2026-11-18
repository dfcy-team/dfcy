"""Register one country coordinator without replaying failed order lookups."""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.integrations.models import SyncJob, WarehouseAuthorization
from apps.integrations.warehouse_order_job import WarehouseOrderLookupAdapter
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Preview/register existing WMS authorizations in unified warehouse-order scheduling.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=int, required=True)
        parser.add_argument('--actor-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options['actor_id'],
            tenant_id=options['tenant_id'], is_active=True).first()
        if not actor or not check_user_permission(actor, 'integrations.manage'):
            raise CommandError('A current same-tenant integrations manager is required.')
        auths = WarehouseAuthorization.objects.filter(tenant_id=actor.tenant_id,
            status='active', warehouse__tenant_id=actor.tenant_id, warehouse__status='active',
            integration_config__environment='production',
            integration_config__platform__in=['jifeng_wms', 'best_ecapi'],
            integration_config__sync_write_enabled=False).select_related('warehouse', 'integration_config').order_by('pk')
        grouped = {}
        for auth in auths:
            if not integration_values_allowed(actor, 'integrations.manage', platform=auth.provider,
                    environment='production', regions=[auth.external_warehouse_region],
                    config_id=auth.integration_config_id, warehouse_id=auth.warehouse_id):
                continue
            country = (auth.warehouse.country_code or '').upper()
            if country:
                grouped.setdefault(country, []).append(auth)
        results = []
        # Serialize automated registration; never edit an existing operator policy.
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=actor.tenant_id)
            for country, candidates in sorted(grouped.items()):
                existing = list(SyncJob.objects.filter(tenant_id=actor.tenant_id,
                    resource_type='warehouse_order_lookup',
                    warehouse_authorization__warehouse__country_code__iexact=country))
                if len(existing) > 1:
                    raise CommandError('Duplicate country coordinators require operator review.')
                if existing:
                    job = existing[0]
                    results.append({'country': country, 'job_id': job.pk, 'status': 'existing',
                                    'enabled': job.is_enabled})
                    continue
                job = None
                for auth in candidates:
                    candidate = SyncJob(tenant_id=actor.tenant_id, integration_config=auth.integration_config,
                        warehouse_authorization=auth, resource_type='warehouse_order_lookup',
                        schedule_type='interval', is_enabled=True, status='idle', max_retry_count=0,
                        sync_scope={'execution_mode': 'live_readonly', 'warehouse_order_limit': 50,
                            'schedule': {'timezone': 'Asia/Shanghai', 'interval_minutes': 1,
                                         'execution_budget_seconds': 240, 'catch_up': 'skip'}})
                    try:
                        candidate.full_clean(validate_unique=False, validate_constraints=False)
                        WarehouseOrderLookupAdapter(auth.integration_config).validate_configuration(candidate)
                    except Exception:
                        continue
                    job = candidate
                    break
                if job is None:
                    results.append({'country': country, 'status': 'blocked', 'reason': 'NO_VERIFIED_WMS_AUTHORIZATION'})
                    continue
                if options['apply']:
                    job.next_run_at = timezone.now()
                    job.save()
                results.append({'country': country, 'job_id': job.pk, 'status': 'registered' if job.pk else 'eligible',
                    'authorization_id': job.warehouse_authorization_id, 'enabled': job.is_enabled,
                    'interval_minutes': 1, 'per_run_limit': 50})
        self.stdout.write(json.dumps({'applied': options['apply'], 'results': results}))
