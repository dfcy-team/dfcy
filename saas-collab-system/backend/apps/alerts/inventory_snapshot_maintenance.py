"""Schedule bounded ABC and warning snapshot work without replacing published results."""

import json
from datetime import timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management import call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.commerce import country_decisions
from apps.masterdata.models import CountrySiteMaster, InventoryABCRun, InventoryObservationSettings, StoreMaster
from apps.sales_management.inventory_queries import latest_country_inventory
from apps.supply_chain.models import ReplenishmentStrategy

from .models import InventoryWarningRun
from .warning_snapshot import change_token


def _prepare_country(actor, country, now, *, abc_enabled, warning_enabled):
    local = now.astimezone(ZoneInfo(country.timezone))
    cutoff = local.date() - timedelta(days=1)
    with transaction.atomic():
        CountrySiteMaster.objects.select_for_update().get(pk=country.pk)
        abc = InventoryABCRun.objects.filter(tenant_id=actor.tenant_id, country=country, cutoff_date=cutoff)
        if abc_enabled and (local.hour, local.minute) >= (8, 10):
            good_states = ('queued', 'building', 'ready', 'partial')
            failures = list(abc.filter(config__source='daily', status='failed').values_list('created_at', flat=True))
            if not abc.filter(status__in=good_states).exists() and len(failures) < 3 and not any(
                now - attempted < timedelta(hours=1) for attempted in failures
            ):
                abc.create(tenant_id=actor.tenant_id, country=country, cutoff_date=cutoff, config={'source': 'daily'})

        if not warning_enabled:
            return
        warnings = InventoryWarningRun.objects.filter(tenant_id=actor.tenant_id, country=country)
        warnings.filter(status='building', created_at__lt=now - timedelta(minutes=20)).update(
            status='failed', issues=['worker_timeout'], completed_at=now,
        )
        if warnings.filter(status__in=('queued', 'building')).exists():
            return
        if warnings.filter(created_at__gt=now - timedelta(minutes=30)).exists():
            return
        last = warnings.filter(status__in=('ready', 'partial')).order_by('-completed_at', '-pk').first()
        if last and last.config.get('change_token') == change_token(actor.tenant_id, country):
            source = country_decisions._country_inventory_source(actor, country, now)
            facts = list(latest_country_inventory(source).order_by('pk').values(
                'pk', 'source_run_id', 'warehouse_id', 'internal_sku_id', 'available_qty', 'on_hand_qty',
            ))
            signature = sha256(json.dumps(facts, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()
            if last.config.get('inventory_signature') == signature:
                return
        warnings.create(tenant_id=actor.tenant_id, country=country, config={'source': 'maintenance'})


def _run_tenant(tenant_id):
    actor = CustomUser.objects.filter(tenant_id=tenant_id, is_active=True, user_type='internal',
                                      is_superuser=True).order_by('pk').first()
    if not actor:
        return 'no_full_scope_account'
    now = timezone.now()
    policy = InventoryObservationSettings.objects.filter(tenant_id=tenant_id).first()
    abc_enabled = policy is None or policy.abc_enabled
    shops = StoreMaster.objects.filter(tenant_id=tenant_id, status='active',
                                      country_code__iexact=OuterRef('country_code'))
    countries = CountrySiteMaster.objects.filter(tenant_id=tenant_id, status='active').filter(Exists(shops))
    strategy_countries = set(ReplenishmentStrategy.objects.filter(
        tenant_id=tenant_id, active=True,
    ).values_list('country_id', flat=True))
    runnable = []
    for country in countries.order_by('pk'):
        try:
            ZoneInfo(country.timezone)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            continue
        runnable.append(country.pk)
        _prepare_country(actor, country, now, abc_enabled=abc_enabled, warning_enabled=country.pk in strategy_countries)

    abc_runs = InventoryABCRun.objects.filter(tenant_id=tenant_id, country_id__in=runnable)
    abc_runs.filter(status='building', created_at__lt=now - timedelta(hours=2)).update(
        status='failed', issues=['worker_timeout'], completed_at=now,
    )
    abc = abc_runs.filter(status='queued')
    warnings = InventoryWarningRun.objects.filter(tenant_id=tenant_id, country_id__in=strategy_countries & set(runnable),
                                                 status='queued')
    abc_run = abc.order_by('created_at', 'pk').first() if abc_enabled else None
    warning_run = warnings.order_by('created_at', 'pk').first()
    if abc_run and (not warning_run or abc_run.created_at <= warning_run.created_at):
        call_command('rebuild_inventory_abc', tenant_id=tenant_id, country_code=abc_run.country.country_code,
                     actor_id=actor.pk, queued_only=True)
        return 'abc'
    if warning_run:
        call_command('rebuild_inventory_warnings', tenant_id=tenant_id, country_code=warning_run.country.country_code,
                     queued_only=True)
        return 'warnings'
    return 'idle'


def maintain_tenant(tenant_id):
    """Serialize schedulers across VM workers using a connection-owned lock."""
    if connection.vendor != 'mysql':
        return 'unsupported_database'
    key = f'inventory-snapshot-maintenance:{tenant_id}'
    with connection.cursor() as cursor:
        cursor.execute('SELECT GET_LOCK(%s, 0)', [key])
        if cursor.fetchone()[0] != 1:
            return 'busy'
    try:
        return _run_tenant(tenant_id)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT RELEASE_LOCK(%s)', [key])
