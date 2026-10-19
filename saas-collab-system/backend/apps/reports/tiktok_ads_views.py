from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsMarketplaceStoreViewer
from .permissions import IsAnalyticsViewer
from .tiktok_ads_services import daily_spend_report


class DailySpendQuery(serializers.Serializer):
    date_from = serializers.DateField(input_formats=["%Y-%m-%d"])
    date_to = serializers.DateField(input_formats=["%Y-%m-%d"])
    store_id = serializers.IntegerField(min_value=1, required=False)
    advertiser_id = serializers.RegexField(r"^[0-9]{1,64}$", required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("Unsupported report parameters.")
        if not 0 <= (attrs["date_to"] - attrs["date_from"]).days < 31:
            raise serializers.ValidationError("An explicit inclusive range of 1 to 31 days is required.")
        return attrs


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer, IsMarketplaceStoreViewer])
def tiktok_daily_spend(request):
    query = DailySpendQuery(data=request.query_params)
    query.is_valid(raise_exception=True)
    return success_response(daily_spend_report(request.user, query.validated_data))
