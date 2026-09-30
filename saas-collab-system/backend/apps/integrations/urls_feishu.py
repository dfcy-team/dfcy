from django.urls import path

from .views import feishu_health, feishu_mock_callback
from .feishu_events import event_callback


urlpatterns = [
    path("events/<int:tenant_id>/", event_callback, name="feishu-event-callback"),
    path("health/", feishu_health, name="feishu-health"),
    path("mock-callback/", feishu_mock_callback, name="feishu-mock-callback"),
]
