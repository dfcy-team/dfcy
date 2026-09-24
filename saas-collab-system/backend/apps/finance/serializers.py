from rest_framework import serializers

from .models import (
    BankReceiptImport,
    LazadaFinanceWide,
    PlatformFinanceTransaction,
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


class PlatformStatementSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = PlatformStatement
        fields = "__all__"


class FinanceTransactionQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    platform = serializers.CharField(max_length=30, required=False)
    store_id = serializers.IntegerField(min_value=1, required=False)
    currency = serializers.CharField(max_length=8, required=False)
    fee_category = serializers.ChoiceField(choices=PlatformFinanceTransaction.FeeCategory.choices, required=False)
    match_status = serializers.ChoiceField(choices=PlatformFinanceTransaction.MatchStatus.choices, required=False)
    external_order_id = serializers.CharField(max_length=191, required=False)

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
        if attrs.get("platform"):
            attrs["platform"] = attrs["platform"].lower()
        return attrs


class PlatformFinanceTransactionSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)

    class Meta:
        model = PlatformFinanceTransaction
        fields = (
            "id",
            "platform",
            "store_id",
            "store_name",
            "store_code",
            "external_transaction_id",
            "external_order_id",
            "external_order_item_id",
            "seller_sku",
            "raw_fee_name",
            "fee_code",
            "fee_category",
            "raw_amount",
            "signed_amount",
            "currency",
            "occurred_at_utc",
            "business_date",
            "match_status",
        )
        read_only_fields = fields


class LazadaFinanceWideQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    store_id = serializers.IntegerField(min_value=1, required=False)
    currency = serializers.CharField(max_length=8, required=False)
    external_order_id = serializers.CharField(max_length=191, required=False)
    seller_sku = serializers.CharField(max_length=191, required=False)

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


class LazadaFinanceWideSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)

    class Meta:
        model = LazadaFinanceWide
        exclude = ("tenant", "authorization", "source_run", "income_key", "source_hash", "fee_details")


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
