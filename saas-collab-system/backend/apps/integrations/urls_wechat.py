from django.urls import path

from .views import wechat_health, wechat_mock_callback


urlpatterns = [
    path("health/", wechat_health, name="wechat-health"),
    path("mock-callback/", wechat_mock_callback, name="wechat-mock-callback"),
]
