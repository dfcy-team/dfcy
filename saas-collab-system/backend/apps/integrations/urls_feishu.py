from django.urls import path

from .views import feishu_health, feishu_mock_callback


urlpatterns = [
    path("health/", feishu_health, name="feishu-health"),
    path("mock-callback/", feishu_mock_callback, name="feishu-mock-callback"),
]
