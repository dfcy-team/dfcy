from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import CurrentUserSerializer


class MiniAppLoginSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=3, max_length=512, trim_whitespace=True)


class MiniAppRefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(min_length=20, max_length=4096, trim_whitespace=True)

    def validate_refresh_token(self, value):
        try:
            return RefreshToken(value)
        except TokenError as exc:
            raise serializers.ValidationError("The refresh token is invalid or expired.") from exc


class MiniAppCurrentUserSerializer(serializers.Serializer):
    def to_representation(self, instance):
        trusted = CurrentUserSerializer(instance).data
        display_name = instance.username
        if instance.user_type == instance.UserType.EXTERNAL:
            profile = getattr(instance, "external_profile", None)
            if profile and profile.contact_name:
                display_name = profile.contact_name
        return {
            "id": str(instance.id),
            "username": instance.username,
            "displayName": display_name,
            "userType": instance.user_type,
            "tenant": {
                "id": str(instance.tenant_id),
                "name": instance.tenant.name,
            },
            "roles": trusted["roles"],
            "permissions": trusted["permissions"],
            "dataScope": trusted["data_scope"],
        }
