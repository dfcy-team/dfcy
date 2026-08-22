from rest_framework import serializers

from .models import ListingProfile, ListingPublicationJob, ListingTemplate, ListingVariant


class ListingTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingTemplate
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "created_at", "updated_at")

    def validate_platform(self, value):
        if value.tenant_id != self.context["request"].user.tenant_id:
            raise serializers.ValidationError("Platform must belong to the current tenant.")
        return value


class ListingVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingVariant
        fields = "__all__"
        read_only_fields = ("profile",)


class ListingProfileSerializer(serializers.ModelSerializer):
    variants = ListingVariantSerializer(many=True, read_only=True)

    class Meta:
        model = ListingProfile
        fields = "__all__"
        read_only_fields = (
            "tenant", "created_by", "status", "validation_errors", "external_listing_id",
            "approved_by", "approved_at", "created_at", "updated_at",
        )

    def validate(self, attrs):
        tenant_id = self.context["request"].user.tenant_id
        for field in ("product", "store", "template"):
            value = attrs.get(field)
            if value is not None and value.tenant_id != tenant_id:
                raise serializers.ValidationError({field: "Referenced record must belong to the current tenant."})
        return attrs


class ListingPublicationJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingPublicationJob
        fields = "__all__"
