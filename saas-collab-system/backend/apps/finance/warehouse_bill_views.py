import csv
import io
import json

from django.db.models import Count
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from .warehouse_bill_uploads import describe, owned_job, request_operation, require_original, upload_bill
from .warehouse_fee_models import WarehouseBillUpload
from .warehouse_fee_services import PREFIX
from .warehouse_bill_edits import audit_id, match_status, order_lookup
from .models import FinanceAuditLog


class WarehouseBillView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = PREFIX + 'import'
    write_permission_code = PREFIX + 'import'
    operation = ''

    def get(self, request, pk=None):
        require_original(request.user)
        if pk is None:
            jobs = WarehouseBillUpload.objects.filter(tenant=request.user.tenant, uploaded_by=request.user).order_by('-created_at')[:50]
            return success_response({'results': [describe(owned_job(request.user, j.pk)) for j in jobs]})
        job = owned_job(request.user, pk)
        if request.query_params.get('audit_row') is not None:
            number = serializers.IntegerField(min_value=1).run_validation(request.query_params['audit_row'])
            row = job.rows.filter(number=number).first()
            if not row:
                raise ValidationError('当前账单不存在该记录。')
            events = FinanceAuditLog.objects.filter(tenant=request.user.tenant, object_type='warehouse_bill_row',
                object_id=audit_id(job, row)).order_by('-id')[:50]
            return success_response({'results': [{'id': event.pk, 'action': event.action, 'actor': event.actor_id,
                'at': event.created_at, 'detail': event.masked_detail} for event in events]})
        if self.operation == 'errors':
            def content():
                yield '\ufeff'
                stream = io.StringIO()
                writer = csv.writer(stream)
                def line(values):
                    stream.seek(0); stream.truncate()
                    writer.writerow(["'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
                    return stream.getvalue()
                yield line(['工作表', '原行号', '原店铺', '原仓库', '平台订单号', '金额', '币种', '待核对原因'])
                for row in job.rows.filter(status='error').order_by('number').iterator(chunk_size=1000):
                    yield line([row.source.get('sheet'), row.source.get('row'), row.source.get('raw_store'), row.source.get('raw_warehouse'),
                                row.data.get('external_order_id'), row.data.get('amount'), row.data.get('currency'), row.error])
            response = StreamingHttpResponse(content(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="warehouse_bill_errors.csv"'
            return response
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        size = serializers.IntegerField(min_value=1, max_value=100).run_validation(request.query_params.get('page_size', 20))
        rows = job.rows.all()
        status = request.query_params.get('status')
        if status:
            status = serializers.ChoiceField(choices=['valid', 'error', 'created', 'existing']).run_validation(status)
            rows = rows.filter(status=status)
        kind = request.query_params.get('kind')
        if kind:
            rows = rows.filter(data__kind=serializers.ChoiceField(choices=['order', 'other']).run_validation(kind))
        counts = dict(job.rows.values('status').annotate(total=Count('pk')).values_list('status', 'total'))
        page_rows = list(rows.order_by('number')[(page - 1) * size:page * size])
        orders = order_lookup(request.user, page_rows)
        return success_response({**describe(job), 'counts': counts, 'count': rows.count(), 'results': [
            {'number': r.number, 'data': r.data, 'source': r.source, 'error': r.error, 'status': r.status,
             'fee_id': r.fee_id, 'match_status': r.source.get('matching', {}).get('status') or match_status(r.data, orders)} for r in page_rows]})

    def post(self, request, pk=None):
        require_original(request.user)
        if pk is None:
            try:
                supplied = json.loads(request.data.get('options', '{}'))
            except (ValueError, TypeError) as exc:
                raise ValidationError('解析选项不是有效JSON。') from exc
            job = upload_bill(request.user, request.FILES.get('file'), supplied)
        else:
            job = request_operation(request.user, pk, request.data)
        job.refresh_from_db()
        return success_response(describe(job), status=200 if request.data.get('operation') in {'edit', 'restore', 'settle'} else 202)


def bill_endpoint(operation='', *, methods=None):
    return type('WarehouseBillEndpoint', (WarehouseBillView,), {'__module__': __name__, 'operation': operation,
        'http_method_names': methods or ['get', 'post', 'head', 'options']}).as_view()
