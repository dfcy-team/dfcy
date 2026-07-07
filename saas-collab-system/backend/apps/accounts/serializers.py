from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import CustomUser


class InternalTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        if self.user.user_type != CustomUser.UserType.INTERNAL:
            raise serializers.ValidationError("Only internal users can log in here.")
        return data


class CurrentUserSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ("user_id", "username", "email", "user_type", "tenant_id", "roles", "permissions")

    user_id = serializers.IntegerField(source="id", read_only=True)

    def get_roles(self, obj):
        return list(
            obj.user_roles.filter(tenant=obj.tenant, role__status="active")
            .select_related("role")
            .values_list("role__code", flat=True)
            .distinct()
        )

    def get_permissions(self, obj):
        return list(
            obj.user_roles.filter(tenant=obj.tenant, role__status="active")
            .select_related("role")
            .prefetch_related("role__permissions")
            .values_list("role__permissions__code", flat=True)
            .exclude(role__permissions__code__isnull=True)
            .distinct()
        )
