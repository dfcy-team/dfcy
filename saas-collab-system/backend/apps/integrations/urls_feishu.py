from django.urls import path

from .views import feishu_health, feishu_mock_callback
from .feishu_login import (
    FeishuLoginCallbackView, FeishuLoginCompleteView, FeishuLoginConfigView, FeishuLoginStartView,
)


urlpatterns = [
    path("login/config/", FeishuLoginConfigView.as_view(), name="feishu-login-config"),
    path("login/start/", FeishuLoginStartView.as_view(), name="feishu-login-start"),
    path("login/callback/", FeishuLoginCallbackView.as_view(), name="feishu-login-callback"),
    path("login/complete/", FeishuLoginCompleteView.as_view(), name="feishu-login-complete"),
    path("health/", feishu_health, name="feishu-health"),
    path("mock-callback/", feishu_mock_callback, name="feishu-mock-callback"),
]
