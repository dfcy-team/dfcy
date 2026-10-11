from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import paginated_data, success_response
from apps.integrations.models import ShopeeAdvertisingRecord
from apps.integrations.shopee_advertising import DATASETS
from apps.permissions.ui_p6_scopes import filter_analytics_queryset
from .permissions import IsAnalyticsViewer


class AdvertisingQuerySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DATASETS, default="shop_daily")
    store_id = serializers.IntegerField(min_value=1, required=False)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class AdvertisingRecordSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    source_run_id = serializers.CharField(source="source_run.run_id", read_only=True)

    class Meta:
        model = ShopeeAdvertisingRecord
        fields = ["id", "store_id", "store_name", "kind", "report_date", "campaign_id",
                  "currency", "report_timezone", "data", "source_run_id", "updated_at"]


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def advertising_records(request):
    if set(request.query_params) - set(AdvertisingQuerySerializer().fields):
        raise ValidationError("Unknown advertising query parameter.")
    query = AdvertisingQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    values = query.validated_data
    if values.get("period_start") and values.get("period_end") and values["period_start"] > values["period_end"]:
        raise ValidationError("开始日期不能晚于结束日期。")
    queryset = filter_analytics_queryset(
        request.user, ShopeeAdvertisingRecord.objects.filter(tenant=request.user.tenant), "analytics.view",
    )
    stores = list(queryset.order_by("store_id").values("store_id", "store__name").distinct())
    queryset = queryset.filter(kind=values["kind"]).select_related("store", "source_run")
    if values.get("store_id"):
        queryset = queryset.filter(store_id=values["store_id"])
    if values["kind"] in {"shop_daily", "shop_hourly", "campaign_daily", "campaign_hourly"}:
        if values.get("period_start"):
            queryset = queryset.filter(report_date__gte=values["period_start"])
        if values.get("period_end"):
            queryset = queryset.filter(report_date__lte=values["period_end"])
    elif values["kind"] in {"gms_campaign", "gms_item"}:
        # Period aggregates must be matched exactly, not treated as daily rows.
        if values.get("period_start"):
            queryset = queryset.filter(data__period_start=values["period_start"].isoformat())
        if values.get("period_end"):
            queryset = queryset.filter(data__period_end=values["period_end"].isoformat())
    result = paginated_data(
        request, queryset.order_by("-report_date", "-updated_at", "-id"),
        AdvertisingRecordSerializer, page=values["page"], page_size=values["page_size"],
    )
    result.update({"stores": stores, "platform": "shopee", "attribution_days": 7,
                   "notice": "广告报表消耗不等于账单扣费；直接和广泛归因不可相加，店铺与活动日报不可重复汇总。"})
    return success_response(result)
