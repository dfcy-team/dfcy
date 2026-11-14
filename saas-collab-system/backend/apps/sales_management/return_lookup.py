"""Explicit single-case lookup, using only authorized read-only WMS endpoints."""
from time import monotonic

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.models import WarehouseAuthorization
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from apps.permissions.services import check_user_permission
from .aftersales import MANAGE, audit, ingest_receipt, outbound_warehouse, require_full_scope, visible_cases


def query_return(user, case):
    require_full_scope(user)
    if case.requires_return is not True or case.return_status == 'cancelled':
        raise ValidationError('请先确认需要实物回仓；已取消售后不可查询关联。')
    if not case.tracking_no and not case.warehouse_return_no:
        raise ValidationError('缺少退货运单号或仓库退货单号，请先采集或核对后填写。')
    outbound = outbound_warehouse(case.order)
    warehouse_id = case.warehouse_id or (outbound.pk if outbound else None)
    if not warehouse_id:
        raise ValidationError('尚未确认订单实际出库仓库，请先补齐出库信息或核对预期退货仓库。')
    if outbound and case.warehouse_id and case.warehouse_id != outbound.pk and not case.expectation_reviewed:
        raise ValidationError('预期退货仓库与实际出库仓库不一致，请先核对。')
    authorizations = WarehouseAuthorization.objects.filter(tenant=user.tenant,
        warehouse__tenant=user.tenant, warehouse__country_code=case.store.country_code,
        provider__in=['jifeng_wms', 'best_ecapi'], status='active').select_related('integration_config', 'warehouse')
    authorizations = authorizations.filter(warehouse_id=warehouse_id)
    authorizations = list(authorizations.order_by('warehouse_id', 'pk'))
    if any(auth.provider == 'best_ecapi' for auth in authorizations) and (
            not case.expectation_reviewed or not case.warehouse_return_no):
        raise ValidationError('百世须先核对仓库退货单号，不以运单号或平台售后号代替。')
    checks, matches = [], []
    started = monotonic()
    for auth in authorizations:
        if monotonic() - started > 60:
            checks.append({'status': 'incomplete'})
            break
        check = {'warehouse_id': auth.warehouse_id, 'status': 'failed'}
        try:
            # Each client's preflight retains network approval and token checks.
            if auth.provider == 'best_ecapi':
                result = query_best_return(user, auth, case)
            else:
                result = JifengWmsReadonlyClient(auth.integration_config, auth).fetch_return_detail(
                    **({'tracking_no': case.tracking_no} if case.tracking_no else {'return_no': case.warehouse_return_no}))
            if result.get('platform_order_no') and (
                    not case.order_id or result['platform_order_no'] != case.order.external_order_id):
                check['status'] = 'identity_conflict'
            else:
                check['status'] = 'matched'
                matches.append((auth, result))
        except ValidationError as exc:
            if exc.get_codes() in (['return_not_found'], ['return_warehouse_mismatch']):
                check['status'] = 'not_found'
        except Exception:
            # Never persist provider exception text, which can contain credentials.
            pass
        checks.append(check)
    blocked = any(row['status'] not in {'matched', 'not_found'} for row in checks)
    status = ('no_authorization' if not checks else 'incomplete' if blocked else
              'ambiguous' if len(matches) > 1 else 'matched' if matches else 'not_found')
    with transaction.atomic():
        user.refresh_from_db()
        if not user.is_active or not check_user_permission(user, MANAGE):
            raise ValidationError('查询期间操作权限已变化。')
        require_full_scope(user)
        current = visible_cases(user, MANAGE).select_for_update().get(pk=case.pk)
        if (current.version, current.tracking_no, current.warehouse_id) != (case.version, case.tracking_no, case.warehouse_id):
            raise ValidationError('查询期间售后信息已变化，请刷新后重试。')
        if not case.warehouse_id:
            latest = outbound_warehouse(current.order)
            if latest is None or latest.pk != warehouse_id:
                raise ValidationError('查询期间出库仓库已变化，请刷新后重试。')
        current.last_checked_at = timezone.now()
        current.save(update_fields=['last_checked_at', 'updated_at'])
        if status == 'matched':
            auth, result = matches[0]
            identity = (auth.tenant_id, auth.warehouse_id, auth.integration_config_id, auth.external_warehouse_code)
            auth.refresh_from_db()
            if auth.status != 'active' or identity != (
                    auth.tenant_id, auth.warehouse_id, auth.integration_config_id, auth.external_warehouse_code):
                raise ValidationError('查询期间仓库授权已变化，请重新核对。')
            current.warehouse_id = auth.warehouse_id
            current.version += 1
            current.save(update_fields=['warehouse', 'version', 'updated_at'])
            if any(row['received_quantity'] > 0 for row in result['lines']):
                ingest_receipt(user, auth.warehouse, result, source='api')
        report = {'status': status, 'checks': checks}
        audit(user, current, 'return_warehouse_queried', after=report)
    return report


def query_best_return(user, auth, case):
    from apps.integrations.best_business import request_payload, return_receipt, text
    from apps.integrations.warehouse_api_service import execute_operation
    from apps.permissions.ui_p6_scopes import integration_values_allowed
    if not case.expectation_reviewed or not case.warehouse_return_no:
        raise ValidationError('百世须先核对仓库退货单号，不以运单号或平台售后号代替。')
    if not integration_values_allowed(user, 'integrations.warehouse.view', platform=auth.provider,
            environment=auth.integration_config.environment, regions=[auth.external_warehouse_region],
            config_id=auth.integration_config_id, warehouse_id=auth.warehouse_id):
        raise ValidationError('百世仓库不在查看范围内。')
    number = text(case.warehouse_return_no)
    result = execute_operation(actor=user, authorization=auth, name='GET_RMA_STATUS_REQ',
        payload=request_payload(auth, rmaCode=number))
    # Response only identifies rmaCode. Keep platform/tracking fields blank;
    # allocation uses the explicitly reviewed warehouse + return-number binding.
    return return_receipt(result['data'], number)
