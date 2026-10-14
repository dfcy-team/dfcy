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
    platforms = serializers.CharField(max_length=120, required=False, allow_blank=False)
    store_id = serializers.IntegerField(min_value=1, required=False)
    store_ids = serializers.CharField(max_length=500, required=False, allow_blank=False)
    raw_fee_name = serializers.CharField(max_length=191, required=False, allow_blank=False)
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
        for key, max_items in (("store_ids", 50), ("platforms", 10)):
            if key not in attrs:
                continue
            values = [value.strip() for value in attrs[key].split(",")]
            if not values or any(not value for value in values) or len(values) > max_items:
                raise serializers.ValidationError({key: f"Provide 1 to {max_items} comma-separated values."})
            if key == "store_ids":
                if any(not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63 for value in values):
                    raise serializers.ValidationError({key: "Store IDs must be positive integers."})
                attrs[key] = list(dict.fromkeys(int(value) for value in values))
            else:
                attrs[key] = list(dict.fromkeys(value.lower() for value in values))
                if any(len(value) > 30 for value in attrs[key]):
                    raise serializers.ValidationError({key: "Platform values must be at most 30 characters."})
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


class FinanceLegacyListQuerySerializer(serializers.Serializer):
    platform = serializers.CharField(max_length=40, required=False)
    currency = serializers.CharField(max_length=10, required=False)
    status = serializers.CharField(max_length=30, required=False)

    def to_internal_value(self, data):
        unknown = set(data.keys()) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown query parameter." for key in sorted(unknown)})
        attrs = super().to_internal_value(data)
        if attrs.get("platform"):
            attrs["platform"] = attrs["platform"].lower()
        if attrs.get("currency"):
            attrs["currency"] = attrs["currency"].upper()
        return attrs


class ManualReconciliationMatchSerializer(serializers.Serializer):
    statement_id = serializers.IntegerField(min_value=1)
    withdrawal_id = serializers.IntegerField(min_value=1)
    bank_receipt_id = serializers.IntegerField(min_value=1)

    def to_internal_value(self, data):
        unknown = set(data.keys()) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown field." for key in sorted(unknown)})
        return super().to_internal_value(data)


class ReconciliationExceptionResolveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)

    def to_internal_value(self, data):
        unknown = set(data.keys()) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown field." for key in sorted(unknown)})
        return super().to_internal_value(data)


class ReconciliationMatchDetailSerializer(ReconciliationMatchSerializer):
    statement = PlatformStatementSerializer(read_only=True)
    withdrawal = WithdrawalRecordSerializer(read_only=True)
    bank_receipt = BankReceiptImportSerializer(read_only=True)
    statement_no = serializers.CharField(source="statement.statement_no", read_only=True)
    withdrawal_no = serializers.CharField(source="withdrawal.withdrawal_no", read_only=True)
    receipt_reference = serializers.CharField(source="bank_receipt.reference_no", read_only=True)
    platform = serializers.CharField(source="statement.platform", read_only=True)
    currency = serializers.CharField(source="statement.currency", read_only=True)
    statement_net_amount = serializers.DecimalField(source="statement.net_amount", max_digits=12, decimal_places=2, read_only=True)
    withdrawal_expected_amount = serializers.DecimalField(source="withdrawal.expected_amount", max_digits=12, decimal_places=2, read_only=True)
    receipt_amount = serializers.DecimalField(source="bank_receipt.receipt_amount", max_digits=12, decimal_places=2, read_only=True)

    class Meta(ReconciliationMatchSerializer.Meta):
        fields = ReconciliationMatchSerializer.Meta.fields + (
            "statement_no", "withdrawal_no", "receipt_reference", "platform", "currency",
            "statement_net_amount", "withdrawal_expected_amount", "receipt_amount",
        )
