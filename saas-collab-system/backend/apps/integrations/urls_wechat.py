from django.urls import path

from .views import wechat_health


urlpatterns = [
    path("health/", wechat_health, name="wechat-health"),
]
