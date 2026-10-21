from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer
from . import tiktok_ads_oauth as service


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({"non_field_errors": ["广告授权提交内容不正确，请返回原店铺重试。"]})
        return super().to_internal_value(data)


class StartInput(StrictInput):
    store_id = serializers.IntegerField(min_value=1)
    integration_config_id = serializers.IntegerField(min_value=1)


class CompleteInput(StrictInput):
    session_id = serializers.UUIDField()
    receipt_id = serializers.RegexField(r"^[0-9a-f]{64}$")


class BindInput(StrictInput):
    advertiser_ids = serializers.ListField(child=serializers.RegexField(r"^[0-9]{1,64}$"), min_length=1, max_length=500)
    idempotency_key = serializers.CharField(min_length=8, max_length=128)

    def validate_advertiser_ids(self, values):
        if len(set(values)) != len(values):
            raise ValidationError("所选广告账户重复，请重新选择。")
        return values


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def start(request):
    data = StartInput(data=request.data)
    data.is_valid(raise_exception=True)
    return success_response(service.start(request.user, data.validated_data["store_id"], data.validated_data["integration_config_id"]), status=201)


@transaction.non_atomic_requests
@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def complete(request):
    data = CompleteInput(data=request.data)
    data.is_valid(raise_exception=True)
    return success_response(service.complete(request.user, **data.validated_data))


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def detail(request, session_id):
    return success_response(service.sanitized(service.load(request.user, session_id, read_only=True)))


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def discover(request, session_id):
    StrictInput(data=request.data).is_valid(raise_exception=True)
    return success_response(service.discover(request.user, session_id))


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def verify(request, session_id, advertiser_id):
    StrictInput(data=request.data).is_valid(raise_exception=True)
    return success_response(service.verify(request.user, session_id, advertiser_id))


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def bind(request, session_id):
    data = BindInput(data=request.data)
    data.is_valid(raise_exception=True)
    return success_response(service.bind(request.user, session_id, **data.validated_data))
