from rest_framework import serializers

from .models import MarketplaceOAuthAttempt


class MarketplaceOAuthAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketplaceOAuthAttempt
        fields = (
            "id", "platform", "store_id", "region", "redirect_target_code", "status",
            "expires_at", "consumed_at", "last_error_code", "request_id", "contract_version",
        )
        read_only_fields = fields
