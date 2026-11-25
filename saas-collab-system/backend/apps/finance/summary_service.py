"""Local SaaS adapter for the accepted HTML2 accounting batch.

Inputs are immutable and private. Only validated settings are changed; posting an
adjustment never rewrites marketplace or warehouse source records.
"""
import hashlib
import base64
import gzip
import json
from pathlib import Path
import shutil
import subprocess

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Count
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .summary_scopes import permission_allowed, permission_scopes
from .models import FinanceAuditLog
from .summary_models import FinanceSummaryDataset, FinanceSummaryState

READ_PERMISSIONS = ('finance.view', 'finance.gcash.view', 'finance.warehouse_fees.view',
                    'sales_management.orders.view', 'sales_management.promotion.view', 'products.cost.view')
STATE_KEYS = {'saas-finance-source-participation-v1', 'finance-preview-fee-checkboxes-v1', 'html2-ledger-fees-v1',
              'html2-shopee-recharge-v1', 'html2-lazada-tax-rules-v1',
              'html2-lazada-amortization-v1', 'html2-profit-closed-periods-v1'}


def pack_values(values):
    return {key: value if len(value) < 100_000 else {
        'encoding': 'gzip-base64-v1', 'sha256': hashlib.sha256(value.encode()).hexdigest(),
        'data': base64.b64encode(gzip.compress(value.encode())).decode('ascii')}
        for key, value in values.items()}


def unpack_values(values):
    result = {}
    try:
        for key, value in values.items():
            if isinstance(value, str):
                result[key] = value
            else:
                if value['encoding'] != 'gzip-base64-v1':
                    raise ValueError()
                text = gzip.decompress(base64.b64decode(value['data'], validate=True)).decode('utf-8')
                if hashlib.sha256(text.encode()).hexdigest() != value['sha256']:
                    raise ValueError()
                result[key] = text
    except (KeyError, ValueError, OSError, TypeError):
        raise ValidationError('财务设置存储校验失败，请恢复已保存备份；未按空账继续计算。')
    return result


def has_full_scope(user, code):
    return permission_allowed(user, code) and (user.is_superuser or any(
        s['scope_type'] == 'all' for s in permission_scopes(user, code)))


def require_access(user, *, write=False):
    if any(not permission_allowed(user,code) or not permission_scopes(user,code) for code in READ_PERMISSIONS):
        raise PermissionDenied('平台账单需要财务、订单、推广、GCash、仓库费用和商品成本的查看权限。')
    if write and (any(not has_full_scope(user,code) for code in READ_PERMISSIONS) or not has_full_scope(user,'finance.import')):
        raise PermissionDenied('修改共享账务设置或重算需要完整查看范围及 finance.import 权限。')


def dataset_for(user, pk=None):
    require_access(user)
    qs = FinanceSummaryDataset.objects.filter(tenant=user.tenant, active=True)
    dataset = qs.filter(pk=pk).first() if pk else qs.order_by('-pk').first()
    if not dataset:
        raise NotFound('本租户尚未接入已验收财务批次，或原批次已更新，请刷新页面。')
    return dataset


def private_root():
    return Path(getattr(settings, 'FINANCE_SUMMARY_ROOT', Path(settings.BASE_DIR).parent / 'private-data' / 'finance-summary'))


def document_path(dataset):
    root = private_root().resolve()
    file = (root / dataset.document_file).resolve()
    if file.parent != root or not file.is_file():
        raise ValidationError('财务批次文件不可用，请恢复原始批次。')
    return file


def engine(dataset, payload):
    node = getattr(settings, 'FINANCE_SUMMARY_NODE', None) or shutil.which('node')
    if not node:
        raise ValidationError('财务计算运行时不可用，未保存任何修改。')
    worker = Path(__file__).with_name('summary_worker.cjs')
    try:
        proc = subprocess.run([node, '--max-old-space-size=2048', str(worker), str(document_path(dataset))],
                              input=json.dumps({**payload, 'sourceHash': dataset.source_hash}, ensure_ascii=False), text=True, encoding='utf-8',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ValidationError('财务计算未成功完成，未保存修改。请稍后重试。')
    if proc.returncode or not result.get('ok'):
        raise ValidationError(result.get('error', '财务计算失败，未保存修改。'))
    return result['result']


def checkpoint_aggregate(queryset, stamp):
    """Use the measured covering index only for the MySQL item checkpoint."""
    from django.db import connections, DatabaseError
    connection=connections[queryset.db]
    if connection.vendor=='mysql' and queryset.model._meta.label=='commerce.SalesOrderItem' and stamp:
        query=queryset.order_by().values('id',stamp)
        sql,params=query.query.get_compiler(using=queryset.db).as_sql()
        table=connection.ops.quote_name(queryset.model._meta.db_table)
        sql=sql.replace('FROM '+table,'FROM '+table+' FORCE INDEX ('+connection.ops.quote_name('idx_items_order_stamp')+')',1)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT COUNT('+connection.ops.quote_name('id')+'), MAX('+connection.ops.quote_name(stamp)+') FROM ('+sql+') checkpoint_rows',params)
                count,last=cursor.fetchone()
            if last is not None and settings.USE_TZ:
                from django.utils import timezone
                if timezone.is_naive(last):last=timezone.make_aware(last,connection.timezone)
            return {'count':count,'last':last}
        except DatabaseError as error:
            if not error.args or error.args[0]!=1176:
                raise
            # Safe during rolling deployment before the covering-index migration.
    return queryset.aggregate(count=Count('pk'), **({'last':Max(stamp)} if stamp else {}))


def source_checkpoint(store_ids):
    from apps.commerce.models import SalesOrderItem, SalesOrder, RefundReturn, ShipmentRecord
    from apps.sales_management.aftersales_models import AftersalesCase, WarehouseReturnReceipt
    from apps.influencers.models import SampleFulfillment
    from apps.integrations.models import ShopeeAdvertisingRecord, SyncRawEnvelope, MarketplaceStoreAuthorization
    from apps.integrations.lazada_api_models import LazadaAdvertisingDailySpend, LazadaApiSnapshot
    from .models import PlatformFinanceTransaction
    from .warehouse_fee_models import WarehouseFee, WarehouseBillUpload
    from apps.sales_management.registration_models import OrderRegistration, PendingOrderDetail
    from apps.products.models import ProductCostVersion, ProductSKU
    from apps.listings.models import PlatformProductDetail
    from apps.masterdata.models import StoreMaster
    from .summary_models import FinanceSummaryInput
    from apps.masterdata.models import DailyExchangeRateSnapshot
    tenant_ids = StoreMaster.objects.filter(pk__in=store_ids).values_list('tenant_id', flat=True).distinct()
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    rows = {
        'warehouse_shipments': OrderWarehouseLookup.objects.filter(order__tenant_id__in=tenant_ids, order__store_id__in=store_ids),
        'stores': StoreMaster.objects.filter(pk__in=store_ids),
        'provider_stores': MarketplaceStoreAuthorization.objects.filter(store_id__in=store_ids, status='active'),
        'platform_finance': PlatformFinanceTransaction.objects.filter(store_id__in=store_ids),
        'orders': SalesOrder.objects.filter(store_id__in=store_ids),
        'order_items': SalesOrderItem.objects.filter(sales_order__store_id__in=store_ids),
        'cost_refunds': RefundReturn.objects.filter(store_id__in=store_ids),
        'cost_aftersales': AftersalesCase.objects.filter(store_id__in=store_ids),
        'cost_return_receipts': WarehouseReturnReceipt.objects.filter(tenant_id__in=tenant_ids),
        'cost_shipments': ShipmentRecord.objects.filter(store_id__in=store_ids),
        'cost_samples': SampleFulfillment.objects.filter(store_id__in=store_ids),
        'shopee_ads': ShopeeAdvertisingRecord.objects.filter(store_id__in=store_ids),
        'lazada_ads': LazadaAdvertisingDailySpend.objects.filter(store_id__in=store_ids),
        'lazada_queries': LazadaApiSnapshot.objects.filter(authorization__store_id__in=store_ids),
        'warehouse_fees': WarehouseFee.objects.filter(tenant_id__in=tenant_ids),
        'warehouse_bills': WarehouseBillUpload.objects.filter(tenant_id__in=tenant_ids),
        'registrations': OrderRegistration.objects.filter(store_id__in=store_ids),
        'adjusted_items': PendingOrderDetail.objects.filter(order__store_id__in=store_ids),
        'cost_versions': ProductCostVersion.objects.filter(tenant_id__in=tenant_ids),
        'skus': ProductSKU.objects.filter(tenant_id__in=tenant_ids),
        'catalogue': PlatformProductDetail.objects.filter(store_id__in=store_ids),
        'provider_responses': SyncRawEnvelope.objects.filter(store_id__in=store_ids),
        'reviewed_inputs': FinanceSummaryInput.objects.filter(tenant_id__in=tenant_ids),
        'daily_exchange_rates': DailyExchangeRateSnapshot.objects.filter(tenant_id__in=tenant_ids),
    }
    result = {}
    for name, qs in rows.items():
        fields = {f.name for f in qs.model._meta.fields}
        stamp = next((f for f in ['updated_at', 'updated_at_utc', 'checked_at', 'snapshot_at', 'created_at', 'ingested_at'] if f in fields), None)
        aggregate = checkpoint_aggregate(qs,stamp)
        result[name] = {'count': aggregate['count'], 'latest': str(aggregate['last']) if stamp else None}
    return result


def metadata(dataset, user, *, checkpoint=True, include_values=True, lightweight=False):
    from .summary_scopes import full_reader, store_ids, signature
    from apps.masterdata.models import StoreMaster
    full = full_reader(user)
    visible = store_ids(user) if not full else list(StoreMaster.objects.filter(tenant=user.tenant).values_list('pk',flat=True))
    access_signature = signature(user,sorted(visible))
    state = FinanceSummaryState.objects.only('revision').get(dataset=dataset) if lightweight else dataset.accounting_state
    # Database batches are checked by the scheduler; page polling only reads
    # accepted versions and job status, never scans all source tables again.
    check_sources = full and checkpoint and not dataset.metadata.get('database_scope') and dataset.metadata.get('automatic_update_enabled', True)
    try:
        document_path(dataset)
        source_available = True
    except ValidationError:
        source_available = False
    from .summary_models import FinanceSummaryCalculation
    latest = FinanceSummaryCalculation.objects.filter(dataset=dataset, tenant=dataset.tenant, kind='rebuild').only(
        'id', 'status', 'request', 'error_code').order_by('-pk').first()
    from .summary_jobs import queue_status
    refresh_job = ({'id': latest.pk, 'status': latest.status, 'error_code': latest.error_code,
                    **queue_status(latest.status, latest.request)} if latest else None)
    from .summary_health import automation_health
    health = automation_health(dataset)
    if lightweight:
        return {'automation_health':health,'access_signature':access_signature, 'lightweight': True, 'tenant_id': str(dataset.tenant_id), 'dataset': dataset.pk,
                'revision': state.revision, 'source_available': source_available,
                'can_edit': full and has_full_scope(user, 'finance.import'), 'refresh_job': refresh_job,
                'automatic_update_enabled': dataset.metadata.get('automatic_update_enabled', True)}
    jobs = list(FinanceSummaryCalculation.objects.filter(tenant=dataset.tenant, kind='rebuild').order_by('-pk').values(
        'id', 'dataset_id', 'result_dataset_id', 'status', 'error_code', 'created_at', 'finished_at')[:10]) if full else []
    from .summary_recent import recent_scope
    return {'automation_health':health,'access_signature':access_signature,'can_view_settings':full,'tenant_id': str(dataset.tenant_id), 'refresh_job': refresh_job,
            'automation': {'mode': 'server', 'enabled': dataset.metadata.get('automatic_update_enabled', True), 'interval_seconds': 300,
                          'merge_window_seconds': 60,
                          'scope': recent_scope(dataset.metadata.get('store_ids', []) if full else [pk for pk in dataset.metadata.get('store_ids',[]) if pk in visible])}, 'rebuild_history': jobs,
            'scope_stores': list(StoreMaster.objects.filter(tenant=dataset.tenant,pk__in=visible).order_by('code').values('id', 'code')),
            'source_available': source_available, 'dataset': dataset.pk, 'label': dataset.label, 'source_hash': dataset.source_hash,
            'imported_at': dataset.created_at.isoformat(), 'source': dataset.metadata if full else {'data_origin':dataset.metadata.get('data_origin'),'database_scope':{**(dataset.metadata.get('database_scope') or {}),'stores':[pk for pk in dataset.metadata.get('store_ids',[]) if pk in visible]}},
            'source_checked': bool(check_sources),
            'source_changed': source_checkpoint(dataset.metadata['store_ids']) != dataset.metadata.get('checkpoint') if check_sources else None,
            'revision': state.revision, **({'values': unpack_values(state.values)} if include_values and full else {}), 'can_edit': full and has_full_scope(user, 'finance.import')}


def save_state(dataset, user, *, revision, key, value, reason):
    require_access(user, write=True)
    if key not in STATE_KEYS or not isinstance(value, str) or len(value) > 2_000_000:
        raise ValidationError('不支持的设置或记录过大。')
    if not reason or not reason.strip() or len(reason) > 1000:
        raise ValidationError('请填写操作原因，最多1000字。')
    try:
        json.loads(value)
    except ValueError:
        raise ValidationError('设置不是有效的JSON。')
    with transaction.atomic():
        if not FinanceSummaryDataset.objects.select_for_update().filter(pk=dataset.pk, tenant=user.tenant, active=True).exists():
            return None
        # Serialize settings, exclusions, and close operations in one revision.
        state = FinanceSummaryState.objects.select_for_update().get(dataset=dataset)
        if revision != state.revision:
            return None
        current = unpack_values(state.values)
        verified = engine(dataset, {'action': 'save', 'state': current, 'key': key, 'value': value, 'reason': reason})
        for history_key in {'html2-ledger-fees-v1', 'saas-finance-source-participation-v1'} & verified['values'].keys():
            saved = json.loads(verified['values'][history_key])
            if saved.get('history'):
                saved['history'][-1]['actor'] = {'id': str(user.pk), 'name': user.full_name or user.username}
                saved['history'][-1]['revision'] = state.revision + 1
                verified['values'][history_key] = json.dumps(saved, ensure_ascii=False)
        before = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
        updated = {**current, **verified['values']}
        state.values = pack_values(updated)
        state.revision += 1
        state.updated_by = user
        state.save(update_fields=['values', 'revision', 'updated_by', 'updated_at'])
        FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, action='summary_setting',
            object_type='finance_summary', object_id=str(dataset.pk), masked_detail={
                'key': key, 'reason': reason, 'revision': state.revision, 'before_hash': before,
                'after_hash': hashlib.sha256(json.dumps(updated, sort_keys=True).encode()).hexdigest()})
    return {'dataset': dataset.pk, 'revision': state.revision, 'values': updated}
