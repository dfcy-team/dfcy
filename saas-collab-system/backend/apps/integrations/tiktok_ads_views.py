"""Authenticated Ads direct endpoints; legacy endpoints remain available."""
from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer
from . import tiktok_ads_direct, tiktok_ads_oauth
from .tiktok_ads_oauth_api import StrictInput, StartInput as LegacyStartInput


class StartInput(LegacyStartInput):
    tiktok_browser_verifier = serializers.RegexField(r"^[A-Za-z0-9_-]{43,128}$", required=False,
        trim_whitespace=False, write_only=True)


class DirectInput(StrictInput):
    browser_token = serializers.CharField(max_length=8192, trim_whitespace=False, write_only=True)
    browser_verifier = serializers.RegexField(r"^[A-Za-z0-9_-]{43,128}$", trim_whitespace=False, write_only=True)
    callback_params = serializers.JSONField(write_only=True)


def response(data, status=200):
    result = success_response(data, status=status)
    result["Cache-Control"] = "no-store"
    result["Referrer-Policy"] = "no-referrer"
    return result


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def start(request):
    data = StartInput(data=request.data)
    data.is_valid(raise_exception=True)
    values = dict(data.validated_data)
    values["config_id"] = values.pop("integration_config_id")
    return response(tiktok_ads_oauth.start(request.user, **values), status=201)


@transaction.non_atomic_requests
@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def direct_callback(request):
    data = DirectInput(data=request.data)
    data.is_valid(raise_exception=True)
    return response(tiktok_ads_direct.complete(request.user, **data.validated_data))
