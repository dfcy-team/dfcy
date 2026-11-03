from datetime import timedelta
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsFinanceViewer
from .ledger import KINDS, report


class LedgerQuery(serializers.Serializer):
    view = serializers.ChoiceField(choices=['detail', 'country', 'store', 'order'], default='detail')
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    all_history = serializers.BooleanField(default=False)
    country = serializers.RegexField(r'^[A-Z]{2}$', required=False)
    platform = serializers.CharField(max_length=40, required=False)
    store_id = serializers.IntegerField(min_value=1, required=False)
    warehouse_id = serializers.IntegerField(min_value=1, required=False)
    external_order_id = serializers.CharField(max_length=1000, required=False)
    currency = serializers.RegexField(r'^[A-Z]{3}$', required=False)
    kind = serializers.ChoiceField(choices=KINDS, required=False)
    status = serializers.ChoiceField(choices=['confirmed', 'pending', 'reference'], required=False)
    source = serializers.ChoiceField(choices=['平台结算', '广告账单', 'GCash登记', '订单推广登记', '仓库账单'], required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    breakdown = serializers.BooleanField(default=False)

    def validate(self, value):
        if not value['all_history'] and not value.get('period_start') and not value.get('period_end'):
            value.update(period_start=timezone.localdate() - timedelta(days=29), period_end=timezone.localdate())
        if value.get('period_start') and value.get('period_end') and value['period_start'] > value['period_end']:
            raise ValidationError('开始日期不能晚于结束日期。')
        return value


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
def finance_ledger(request):
    query = LedgerQuery(data=request.query_params)
    if set(request.query_params) - set(query.fields):
        raise ValidationError('包含未支持的查询字段。')
    query.is_valid(raise_exception=True)
    # DRF's bare Decimal rendering uses floats; money remains exact text on the wire.
    return success_response(json.loads(json.dumps(report(request.user, query.validated_data), cls=DjangoJSONEncoder)))
