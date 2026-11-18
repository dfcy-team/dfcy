"""Native SyncJob coordinator for requested orders, preserving per-order truth."""
from collections import Counter

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .adapters import PlatformAdapter
from .models import SyncJob, WarehouseAuthorization


class WarehouseOrderLookupAdapter(PlatformAdapter):
    adapter_name = 'warehouse-order-lookup'
    execution_mode = 'live_readonly'
    FAILURE_STATES = {'partial', 'failed', 'blocked', 'conflict', 'stopped'}
    STATES = FAILURE_STATES | {'matched', 'not_found', 'deferred', 'superseded', 'already_running'}

    def __init__(self, config):
        self.config = config
        self.scope = {}
        self.summary = Counter()
        self.source_run = None
        self.readiness = {}
        self.permission_cache = {}

    def validate_configuration(self, job):
        if not getattr(settings, 'SALES_ORDER_WAREHOUSE_SYNC_ENABLED', False):
            raise ValidationError('WAREHOUSE_LOOKUP_DISABLED')
        if (not getattr(settings, 'WAREHOUSE_BUSINESS_API_ENABLED', False)
                or self.config.status not in {'verified', 'active'}
                or not self.config.network_enabled or not self.config.sync_read_enabled):
            raise ValidationError('WAREHOUSE_LOOKUP_READONLY_APPROVAL_UNAVAILABLE')
        if (job.resource_type != 'warehouse_order_lookup' or job.tenant_id != self.config.tenant_id
                or job.integration_config_id != self.config.pk or job.store_authorization_id or job.ads_mapping_id
                or not job.warehouse_authorization_id or self.config.platform not in {'jifeng_wms', 'best_ecapi'}
                or self.config.environment != 'production' or self.config.sync_write_enabled):
            raise ValidationError('WAREHOUSE_LOOKUP_SCOPE_INVALID')
        auth = WarehouseAuthorization.objects.select_related('warehouse').filter(
            pk=job.warehouse_authorization_id, tenant_id=job.tenant_id,
            integration_config_id=job.integration_config_id, status='active',
            warehouse__tenant_id=job.tenant_id, warehouse__status='active').first()
        if not auth or not auth.warehouse.country_code:
            raise ValidationError('WAREHOUSE_LOOKUP_AUTHORIZATION_UNAVAILABLE')
        from .warehouse_credential_service import require_verified_warehouse
        require_verified_warehouse(auth)
        limit = (job.sync_scope or {}).get('warehouse_order_limit', 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError('WAREHOUSE_LOOKUP_LIMIT_INVALID')
        self.scope = {'warehouse_order_limit': limit,
                      'warehouse_country_code': auth.warehouse.country_code.upper()}

    def bind_run(self, run):
        self.source_run = run
        saved = (run.masked_log or {}).get('warehouse_order_lookup', {})
        self.summary = Counter({key: value for key, value in saved.items()
                                if key in self.STATES and type(value) is int and value >= 0})

    def _still_allowed(self, job):
        return SyncJob.objects.filter(
            pk=job.pk, tenant_id=job.tenant_id, is_enabled=True, status='running',
            integration_config_id=self.config.pk, warehouse_authorization_id=job.warehouse_authorization_id,
            integration_config__status__in=['verified', 'active'],
            integration_config__sync_read_enabled=True, integration_config__network_enabled=True,
            integration_config__sync_write_enabled=False,
            lock_token=self.source_run.run_id, lock_expires_at__gt=timezone.now(),
            warehouse_authorization__status='active', warehouse_authorization__warehouse__status='active',
            warehouse_authorization__warehouse__country_code__iexact=self.scope['warehouse_country_code'],
        ).exists()

    def fetch_page(self, job, cursor_value=None):
        if not self._still_allowed(job):
            raise ValidationError('WAREHOUSE_LOOKUP_STOPPED_OR_SCOPE_CHANGED')
        if sum(self.summary.values()) >= self.scope['warehouse_order_limit']:
            return {'records': [], 'next_cursor': ''}
        from apps.sales_management.warehouse_unified import process_next_lookup
        result = process_next_lookup(job, run_guard=lambda: self._still_allowed(job),
                                     readiness=self.readiness, permission_cache=self.permission_cache)
        if result is None:
            return {'records': [], 'next_cursor': ''}
        if not self.validate_record(result):
            raise ValidationError('WAREHOUSE_LOOKUP_RESULT_INVALID')
        self.summary[result['status']] += 1
        # The cursor counts real processing units; it never represents a source date.
        return {'records': [result], 'next_cursor': str(sum(self.summary.values()))
                if sum(self.summary.values()) < self.scope['warehouse_order_limit'] else ''}

    def normalize_record(self, record):
        return record

    def validate_record(self, record):
        return (isinstance(record, dict) and type(record.get('lookup_id')) is int
                and record.get('status') in self.STATES and type(record.get('queried')) is bool)

    def persist_record(self, job, record):
        # The underlying lookup already committed its own lease-protected result.
        return {'action': 'updated' if record['status'] == 'matched' else 'skipped'}

    def after_page_persist(self, job, page, results):
        self.source_run.masked_log = {**(self.source_run.masked_log or {}),
            'warehouse_order_lookup': dict(self.summary),
            'warehouse_lookup_scope': {'country': self.scope['warehouse_country_code'],
                                       'unit': 'previously_requested_order', 'coverage_certified': False}}
        self.source_run.failed_count = sum(self.summary[state] for state in self.FAILURE_STATES)

    def completion_outcome(self, job):
        if not self._still_allowed(job):
            return {'failed': True, 'error_code': 'WAREHOUSE_LOOKUP_STOPPED_OR_SCOPE_CHANGED',
                    'message': '统一任务已暂停或权限范围改变，本轮未作为成功完成。'}
        incomplete = sum(self.summary[state] for state in self.FAILURE_STATES)
        return {'failed': incomplete > 0,
                'error_code': 'WAREHOUSE_LOOKUP_INCOMPLETE' if incomplete else '',
                'message': '部分订单仓库查询未完成，请查看逐单状态及授权/响应校验结果。' if incomplete else ''}

    def get_next_cursor(self, page):
        return page.get('next_cursor', '')

    def should_continue(self, page, previous_cursor):
        return bool(page.get('next_cursor'))
