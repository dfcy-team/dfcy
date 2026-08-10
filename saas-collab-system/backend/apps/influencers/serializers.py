from rest_framework import serializers

from .models import Influencer


def mask_email(value):
    if not value or "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


class InfluencerSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    contact_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    contact_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    contact_phone_masked = serializers.SerializerMethodField()
    contact_email_masked = serializers.SerializerMethodField()

    class Meta:
        model = Influencer
        fields = ("id", "tenant_id", "code", "name", "platform", "handle", "category", "follower_count",
                  "contact_name", "contact_phone", "contact_email", "contact_phone_masked", "contact_email_masked",
                  "cooperation_status", "status", "notes", "created_at", "updated_at")
        read_only_fields = ("id", "tenant_id", "contact_phone_masked", "contact_email_masked", "created_at", "updated_at")

    def validate_code(self, value):
        request = self.context["request"]
        queryset = Influencer.objects.filter(tenant=request.user.tenant, code=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Code must be unique within the current tenant.")
        return value

    def get_contact_phone_masked(self, obj):
        return f"***{obj.contact_phone[-4:]}" if obj.contact_phone else ""

    def get_contact_email_masked(self, obj):
        return mask_email(obj.contact_email)
