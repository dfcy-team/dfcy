from django.urls import path

from . import internal_readonly_api
from . import internal_sso
from . import internal_token_broker


urlpatterns = [
    path("auth/token/", internal_sso.exchange_token, name="internal-sso-token"),
    path("capabilities/", internal_readonly_api.capabilities, name="internal-readonly-capabilities"),
    path("tiktok-shop-token/", internal_token_broker.tiktok_shop_access_token, name="internal-tiktok-shop-token"),
    path("<str:resource>/", internal_readonly_api.resource_collection, name="internal-readonly-resource"),
]
