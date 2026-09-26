from django.urls import path

from . import internal_readonly_api


urlpatterns = [
    path("capabilities/", internal_readonly_api.capabilities, name="internal-readonly-capabilities"),
    path("<str:resource>/", internal_readonly_api.resource_collection, name="internal-readonly-resource"),
]
