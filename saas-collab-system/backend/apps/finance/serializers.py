from rest_framework import serializers

from .models import (
    BankReceiptImport,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)


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
