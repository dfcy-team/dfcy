from django.urls import path

from .views import feishu_health


urlpatterns = [
    path("health/", feishu_health, name="feishu-health"),
]
