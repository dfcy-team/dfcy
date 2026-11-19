from decimal import Decimal
from django.db import transaction
from rest_framework import serializers
from rest_framework.views import APIView
from apps.audit.services import write_operation_log
from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p2_scopes import require_all_scope
from .models import InventoryObservationSettings

SETTING_FIELDS = ("new_product_observation_days", "abc_enabled", "abc_window_days", "abc_a_percent", "abc_b_percent", "abc_stability_days")


def settings_data(instance):
    return {name: str(getattr(instance, name)) if isinstance(getattr(instance, name), Decimal) else getattr(instance, name) for name in SETTING_FIELDS}


class ObservationSettingsInput(serializers.Serializer):
    new_product_observation_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    abc_enabled = serializers.BooleanField(required=False)
    abc_window_days = serializers.IntegerField(min_value=7, max_value=365, required=False)
    abc_a_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("99.99"), required=False)
    abc_b_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.02"), max_value=Decimal("100"), required=False)
    abc_stability_days = serializers.IntegerField(min_value=1, max_value=14, required=False)

    def validate(self, attrs):
        current = self.context["settings"]
        if attrs.get("abc_a_percent", current.abc_a_percent) >= attrs.get("abc_b_percent", current.abc_b_percent):
            raise serializers.ValidationError("A 类累计占比必须小于 B 类累计占比。")
        return attrs


class InventoryObservationSettingsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.settings.view"
    write_permission_code = "masterdata.settings.manage"

    def get(self, request):
        settings = InventoryObservationSettings.objects.filter(tenant=request.user.tenant).first() or InventoryObservationSettings()
        return success_response(settings_data(settings))

    @transaction.atomic
    def put(self, request):
        require_all_scope(request.user, self.write_permission_code)
        settings, _ = InventoryObservationSettings.objects.get_or_create(tenant=request.user.tenant)
        settings = InventoryObservationSettings.objects.select_for_update().get(pk=settings.pk)
        serializer = ObservationSettingsInput(data=request.data, context={"settings": settings})
        serializer.is_valid(raise_exception=True)
        before = settings_data(settings)
        for name, value in serializer.validated_data.items():
            setattr(settings, name, value)
        settings.save(update_fields=[*serializer.validated_data, "updated_at"])
        after = settings_data(settings)
        write_operation_log(tenant=request.user.tenant, user=request.user, module="masterdata", action="update", object_type="inventory_observation_settings", object_id=settings.pk, before_data=before, after_data=after)
        return success_response(after)
