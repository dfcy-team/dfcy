from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.permissions.services import check_stored_business_read_permission, get_stored_business_read_scopes
from .permissions import IsAnalyticsViewer
from .tiktok_ads_services import daily_spend_report


class IsStoredMarketplaceBusinessViewer(BasePermission):
    """Read stored report facts through the original scoped business grant."""
    permission_code = "integrations.store.view"

    def has_permission(self, request, view):
        user = request.user
        if (request.method not in SAFE_METHODS or not user or not user.is_authenticated
                or not user.is_active or user.user_type != "internal" or not user.tenant_id
                or not check_stored_business_read_permission(user, self.permission_code)):
            return False
        if not get_stored_business_read_scopes(user, self.permission_code):
            raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
        return True


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
@permission_classes([IsAnalyticsViewer, IsStoredMarketplaceBusinessViewer])
def tiktok_daily_spend(request):
    query = DailySpendQuery(data=request.query_params)
    query.is_valid(raise_exception=True)
    return success_response(daily_spend_report(request.user, query.validated_data))
