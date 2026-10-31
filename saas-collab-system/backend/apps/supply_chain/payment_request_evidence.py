"""Approved payment evidence and explicit, exactly-once financial posting."""
import hashlib
from io import BytesIO

from django.db import transaction
from django.http import FileResponse
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from . import costs, services
from .api import key
from .dates import business_date
from .models import domain_write
from .cost_models import PaymentRecord
from .payment_request_models import SupplyPaymentRequest, SupplyPaymentRequestVoucher
from .payment_voucher_models import PaymentVoucher
from .payment_vouchers import _validate_file
from .payment_requests import _source, _current, request_data, finance_allowed
from .permissions import MANAGE, VIEW
from .views import InternalAPI


def _row(actor, kind, pk, request_id, *, write=False):
    _source(actor, kind, pk, MANAGE if write else VIEW)
    qs = SupplyPaymentRequest.objects.filter(tenant_id=actor.tenant_id, kind=kind, source_id=pk, pk=request_id)
    # Keep the lock on the request row only (nullable joins cannot be locked on PostgreSQL).
    if write:
        qs = qs.select_for_update()
    row = qs.first()
    if row is None:
        raise NotFound('付款申请不存在或不在当前单据范围。')
    return row


def _approved(row):
    if row.status == 'cancelled' or not row.approval_id or row.approval.status != 'approved':
        raise ValidationError('仅审批通过且未取消的付款申请可办理。')


def conflict(message):
    return Response({'success': False, 'code': 'CONFLICT', 'message': message, 'data': None}, status=409)


class RequestVouchers(InternalAPI):
    @transaction.atomic
    def post(self, request, kind, pk, request_id):
        actor = request.user
        services._tenant_lock(actor)
        row = _row(actor, kind, pk, request_id, write=True)
        _approved(row)
        idem = key(request)
        name, media, body, digest = _validate_file(request.FILES.get('file'))
        old = row.vouchers.defer('content').filter(idempotency_key=idem).first()
        if old:
            if old.sha256 != digest or old.file_name != name:
                return conflict('此上传标识已用于不同凭证。')
            return Response({'data': request_data(actor, row)})
        if row.payment_id:
            raise ValidationError('申请已入账；新增凭证请在对应付款记录中上传。')
        if row.vouchers.count() >= 20:
            raise ValidationError('每份付款申请最多20份凭证。')
        with domain_write():
            SupplyPaymentRequestVoucher.objects.create(tenant=actor.tenant, created_by=actor, request=row,
                file_name=name, media_type=media, byte_size=len(body), sha256=digest, content=body, idempotency_key=idem)
            row.version += 1
            row.save(update_fields=['version', 'updated_at'])
        return Response({'data': request_data(actor, row)}, status=201)


class RequestVoucherDownload(InternalAPI):
    def get(self, request, kind, pk, request_id, voucher_id):
        row = _row(request.user, kind, pk, request_id)
        file = SupplyPaymentRequestVoucher.objects.filter(request=row, tenant_id=request.user.tenant_id, pk=voucher_id).first()
        if file is None:
            raise NotFound('凭证不存在或不属于该付款申请。')
        body = bytes(file.content)
        if hashlib.sha256(body).hexdigest() != file.sha256:
            raise ValidationError('凭证完整性校验失败。')
        response = FileResponse(BytesIO(body), as_attachment=True, filename=file.file_name, content_type=file.media_type)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class ConfirmInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    date = serializers.DateField()
    reference_number = serializers.CharField(max_length=200, allow_blank=True, required=False, default='')
    notes = serializers.CharField(max_length=1000, allow_blank=True, required=False, default='')

    def validate_date(self, value):
        if value > business_date():
            raise serializers.ValidationError('实际付款日期不能晚于今天。')
        return value


class RequestConfirm(InternalAPI):
    @transaction.atomic
    def post(self, request, kind, pk, request_id):
        actor = request.user
        key(request)
        if not finance_allowed(actor):
            raise PermissionDenied('需要本业务范围的财务核对权限才能确认入账。')
        data = ConfirmInput(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        services._tenant_lock(actor)
        row = _row(actor, kind, pk, request_id, write=True)
        reference = p['reference_number'] or f'PRQ-{row.pk}'
        if row.payment_id:
            old = row.payment
            if (old.date, old.reference_number, old.notes) != (p['date'], reference, p['notes']):
                return conflict('申请已入账，不能用不同付款内容再次确认。')
            return Response({'data': request_data(actor, row)})
        _approved(row)
        if row.version != p['expected_version']:
            return conflict('付款申请或凭证已变化，请刷新后核对。')
        if not row.vouchers.exists():
            raise ValidationError('请先上传实际转账凭证。')
        _current(actor, row)
        state = costs.payment_summary(actor, kind, pk)
        payment_key = f'payment-request-{row.pk}'
        body = {'amount': row.amount, 'payee_account_id': row.payee_account_id, 'date': p['date'],
                'reference_number': reference, 'notes': p['notes'], 'expected_version': state['version']}
        if row.fee_item_id:
            body['fee_item_id'] = row.fee_item_id
        costs.create_payment(actor, kind, pk, body, payment_key)
        payment = PaymentRecord.objects.get(tenant=actor.tenant, idempotency_key=payment_key)
        with domain_write():
            # Stream bounded files one at a time; do not load all binary attachments into a list.
            for file in row.vouchers.order_by('id').iterator(chunk_size=1):
                body = bytes(file.content)
                if hashlib.sha256(body).hexdigest() != file.sha256:
                    raise ValidationError('凭证完整性校验失败，未入账。')
                PaymentVoucher.objects.create(tenant=actor.tenant, created_by=actor, payment=payment,
                    file_name=file.file_name, media_type=file.media_type, byte_size=file.byte_size,
                    sha256=file.sha256, content=body, idempotency_key=f'payment-request-voucher-{file.pk}')
            row.payment = payment
            row.status = 'paid'
            row.version += 1
            row.save(update_fields=['payment', 'status', 'version', 'updated_at'])
        return Response({'data': request_data(actor, row)})
