from rest_framework import serializers

from .models import (
    BankReceiptImport,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)


class FinanceAnalyticsQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    platform = serializers.CharField(max_length=40, required=False)
    currency = serializers.CharField(max_length=10, required=False)
    status = serializers.CharField(max_length=40, required=False)

    def to_internal_value(self, data):
        unknown = set(data.keys()) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown query parameter." for key in sorted(unknown)})
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs.get("period_start") and attrs.get("period_end") and attrs["period_start"] > attrs["period_end"]:
            raise serializers.ValidationError({"period_end": "Must not be earlier than period_start."})
        if attrs.get("currency"):
            attrs["currency"] = attrs["currency"].upper()
        return attrs


class FinanceCollectionQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    platform = serializers.CharField(max_length=40, required=False)
    currency = serializers.CharField(max_length=3, required=False)
    status = serializers.CharField(max_length=40, required=False)

    def to_internal_value(self, data):
        unknown = set(data.keys()) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown query parameter." for key in sorted(unknown)})
        return super().to_internal_value(data)

    def validate_currency(self, value):
        return value.upper()


class FinanceDemoImportSerializer(serializers.Serializer):
    platform = serializers.CharField(max_length=40, default="mock")
    currency = serializers.RegexField(r"^[A-Za-z]{3}$", default="USD")
    account_hint = serializers.CharField(max_length=80, default="demo-account", write_only=True)

    def validate_currency(self, value):
        return value.upper()


class FinanceReconciliationRunSerializer(serializers.Serializer):
    platform = serializers.CharField(max_length=40, default="mock")
    currency = serializers.RegexField(r"^[A-Za-z]{3}$", default="USD")

    def validate_currency(self, value):
        return value.upper()


class ReconciliationDecisionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ReconciliationExceptionResolutionSerializer(serializers.Serializer):
    resolution_note = serializers.CharField(max_length=1000, trim_whitespace=True)


class PlatformStatementSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = PlatformStatement
        fields = "__all__"


class WithdrawalRecordSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = WithdrawalRecord
        fields = "__all__"


class BankReceiptImportSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = BankReceiptImport
        fields = "__all__"


class ReconciliationMatchSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    reviewed_by_id = serializers.IntegerField(source="reviewed_by.id", read_only=True)

    class Meta:
        model = ReconciliationMatch
        fields = (
            "id",
            "tenant_id",
            "statement",
            "withdrawal",
            "bank_receipt",
            "match_type",
            "matched_amount",
            "difference_amount",
            "confidence",
            "status",
            "reviewed_by_id",
            "reviewed_at",
        )
        read_only_fields = fields


class ReconciliationExceptionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ReconciliationException
        fields = "__all__"
