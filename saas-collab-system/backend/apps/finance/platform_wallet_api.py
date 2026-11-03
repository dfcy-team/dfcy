from datetime import timedelta

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from .platform_wallet_collectors import CAPABILITIES, BALANCE_NOTE
from .platform_wallet_models import PlatformApiWithdrawal, PlatformWalletSync, PlatformWalletCursor
from .platform_wallet_scopes import scoped
from .platform_wallet_service import visible_stores, require_sync


def sync_data(row):
    return {'enabled': row.enabled if row else False, 'interval_minutes': row.interval_minutes if row else 60,
            'activated_at': row.activated_at if row else None, 'next_run_at': row.next_run_at if row else None,
            'last_run_at': row.last_run_at if row else None, 'state': row.state if row else 'idle',
            'last_error_code': row.last_error_code if row else ''}


class WalletAPI(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = 'finance.view'
    write_permission_code = 'finance.import'


class WalletOverview(WalletAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        sync = PlatformWalletSync.objects.filter(tenant=request.user.tenant, actor=request.user).first()
        cursors = {r.store_id: r for r in PlatformWalletCursor.objects.filter(sync=sync)} if sync else {}
        rows = []
        for store in visible_stores(request.user):
            platform = store.platform.platform_type
            cursor = cursors.get(store.pk)
            rows.append({'store_id': store.pk, 'store_name': store.name, 'store_code': store.code,
                         'platform': platform, 'currency': None, 'archive_currency': store.currency, 'balance': None,
                         'balance_status': 'not_verified', 'balance_note': BALANCE_NOTE,
                         'withdrawal_capability': CAPABILITIES.get(platform, {'withdrawals': False, 'note': '尚未核验此平台提款接口。'}),
                         'last_success_at': cursor.last_success_at if cursor else None,
                         'last_error_code': cursor.last_error_code if cursor else ''})
        return success_response({'stores': rows, 'sync': sync_data(sync), 'api_only': True,
            'can_sync': all(check_user_permission(request.user, code) for code in ('finance.import', 'integrations.run_live_readonly')),
            'no_backfill': True})


class WithdrawalQuery(serializers.Serializer):
    platform = serializers.ChoiceField(choices=['shopee', 'lazada', 'tiktok'], required=False)
    store_id = serializers.IntegerField(min_value=1, required=False)
    currency = serializers.RegexField(r'^[A-Z]{3}$', required=False)
    status = serializers.CharField(max_length=80, required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class WalletWithdrawals(WalletAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        serializer = WithdrawalQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        rows = scoped(request.user, PlatformApiWithdrawal.objects.select_related('store__platform'), records=True).filter(
            store_id__in=visible_stores(request.user).values('pk'),
            authorization__tenant=request.user.tenant, authorization__store_id=F('store_id'),
            authorization__integration_config__tenant=request.user.tenant)
        for key, field in {'platform': 'store__platform__platform_type', 'store_id': 'store_id', 'currency': 'currency', 'status': 'raw_status'}.items():
            if key in params:
                rows = rows.filter(**{field: params[key]})
        pager = Paginator(rows.order_by('store__platform__platform_type', 'store__code', 'currency', '-occurred_at_utc', '-pk'), params['page_size'])
        page = pager.get_page(params['page'])
        values = [{
            'id': r.pk, 'platform': r.store.platform.platform_type, 'store_id': r.store_id,
            'store_name': r.store.name, 'store_code': r.store.code, 'withdrawal_no': r.external_id,
            'transaction_type': r.transaction_type, 'currency': r.currency, 'amount': r.original_amount,
            'status': r.raw_status, 'occurred_at_utc': r.occurred_at_utc, 'observed_at_utc': r.observed_at_utc,
            'source_endpoint': r.source_endpoint, 'source': 'platform_api',
            'fee': None, 'received_amount': None, 'completed_at': None,
        } for r in page.object_list]
        return success_response({'items': values, 'pagination': {'page': page.number, 'total': pager.count,
            'page_size': params['page_size']}, 'api_only': True})


class ScheduleInput(serializers.Serializer):
    enabled = serializers.BooleanField()
    interval_minutes = serializers.IntegerField(min_value=15, max_value=1440)

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('不支持自定义历史采集范围。')
        return attrs


class WalletSchedule(WalletAPI):
    http_method_names = ['get', 'post', 'head', 'options']

    def get(self, request):
        return success_response(sync_data(PlatformWalletSync.objects.filter(tenant=request.user.tenant, actor=request.user).first()))

    def post(self, request):
        require_sync(request.user)
        serializer = ScheduleInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            row, _ = PlatformWalletSync.objects.select_for_update().get_or_create(actor=request.user, defaults={'tenant': request.user.tenant})
            if row.tenant_id != request.user.tenant_id:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('同步配置不属于当前租户。')
            row.enabled = serializer.validated_data['enabled']
            if row.enabled and row.activated_at is None:
                row.activated_at = timezone.now()
            row.interval_minutes = serializer.validated_data['interval_minutes']
            row.next_run_at = timezone.now() + timedelta(minutes=row.interval_minutes) if row.enabled else None
            row.save(update_fields=['enabled', 'interval_minutes', 'next_run_at', 'activated_at'])
            from .models import FinanceAuditLog
            FinanceAuditLog.objects.create(tenant=request.user.tenant, actor=request.user,
                action='platform_wallet.schedule', object_type='PlatformWalletSync', object_id=str(row.pk),
                masked_detail={'enabled': row.enabled, 'interval_minutes': row.interval_minutes})
        return success_response(sync_data(row))


class WalletManualSync(WalletAPI):
    http_method_names = ['post', 'options']

    def post(self, request):
        require_sync(request.user)
        from .tasks import enqueue
        with transaction.atomic():
            row, _ = PlatformWalletSync.objects.select_for_update().get_or_create(actor=request.user, defaults={'tenant': request.user.tenant})
            if row.tenant_id != request.user.tenant_id:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('同步配置不属于当前租户。')
            if row.running_until and row.running_until > timezone.now() or row.state == 'queued':
                return success_response({'state': row.state, 'message': '已有同步请求，请勿重复提交。'}, status=202)
            row.state, row.last_error_code = 'queued', ''
            if row.activated_at is None:
                row.activated_at = timezone.now()
            row.save(update_fields=['state', 'last_error_code', 'activated_at'])
            from .models import FinanceAuditLog
            FinanceAuditLog.objects.create(tenant=request.user.tenant, actor=request.user,
                action='platform_wallet.manual_request', object_type='PlatformWalletSync', object_id=str(row.pk))
        dispatched = enqueue(row)
        return success_response({'state': 'queued', 'dispatched': dispatched,
            'message': '同步请求已登记。' if dispatched else '请求已登记，任务队列暂不可用，等待调度重试。'}, status=202)
