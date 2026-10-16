from django.utils import timezone
from .dates import business_date
from rest_framework import serializers


class PurchaseRowInput(serializers.Serializer):
    sku_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, allow_null=True, required=False)
    import_row_number = serializers.IntegerField(min_value=2, required=False, allow_null=True)


class PurchaseInput(serializers.Serializer):
    supplier_id = serializers.IntegerField(min_value=1)
    country_id = serializers.IntegerField(min_value=1)
    source_kind = serializers.ChoiceField(choices=["manual"], default="manual")
    reference_number = serializers.CharField(max_length=120, allow_blank=True, default="")
    order_date = serializers.DateField(default=business_date)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default="")
    lines = PurchaseRowInput(many=True, allow_empty=False)

    def validate_order_date(self, value):
        if value > business_date():
            raise serializers.ValidationError("下单日期不能晚于今天。")
        return value

    def validate_lines(self, value):
        if len(value) > 1000:
            raise serializers.ValidationError("最多 1000 条商品明细。")
        return value

    def validate(self, attrs):
        # These sources must be produced by the import/upstream adapters.
        if self.initial_data.get("source_kind", "manual") != "manual":
            raise serializers.ValidationError("运营拆单接口尚未接入；导入请使用文件预览与提交入口。")
        for row in self.initial_data.get("lines", []):
            if row.get("operating_sources"):
                raise serializers.ValidationError("不能手工填写未经核验的运营来源。")
        return attrs


class VersionInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class PurchaseEditInput(PurchaseInput):
    source_kind = serializers.ChoiceField(choices=["manual", "import"], required=False)

    def validate(self, attrs):
        if any(row.get("operating_sources") for row in self.initial_data.get("lines", [])):
            raise serializers.ValidationError("不能手工填写未经核验的运营来源。")
        return attrs


class MetadataInput(VersionInput):
    reference_number = serializers.CharField(max_length=120, allow_blank=True)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default="")


class SupplierInput(serializers.Serializer):
    code = serializers.SlugField(max_length=80, required=False, allow_blank=True)
    name = serializers.CharField(max_length=160)
    contact_alias = serializers.CharField(max_length=80, allow_blank=True, default="")
    contact_phone = serializers.CharField(max_length=32, allow_blank=True, default="")
    contact_email = serializers.EmailField(allow_blank=True, default="")
    province = serializers.CharField(max_length=80, allow_blank=True, default="")
    city = serializers.CharField(max_length=80, allow_blank=True, default="")
    factory_address = serializers.CharField(max_length=500, allow_blank=True, default="")
    loading_address = serializers.CharField(max_length=500, allow_blank=True, default="")
    tax_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, default=0)
    first_cooperation_date = serializers.DateField(required=False, allow_null=True)
    payment_term_days = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=3650)
    payment_term_start = serializers.ChoiceField(
        choices=["unspecified", "shipment_date", "collection_arrival", "warehouse_arrival", "reconciliation_date"],
        required=False,
    )
    notes = serializers.CharField(max_length=10000, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=["active", "trial", "inactive"], default="active")
    expected_version = serializers.IntegerField(min_value=1, required=False)


class FreightInput(serializers.Serializer):
    code = serializers.CharField(max_length=80, required=False, allow_blank=True)
    name = serializers.CharField(max_length=160)
    contact = serializers.CharField(max_length=120, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, allow_blank=True, default="")
    province = serializers.CharField(max_length=80, allow_blank=True, default="")
    city = serializers.CharField(max_length=80, allow_blank=True, default="")
    address = serializers.CharField(max_length=500, allow_blank=True, default="")
    shipping_marks = serializers.CharField(max_length=500, allow_blank=True, default="")
    fee_per_cbm = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, allow_null=True, default=None)
    tax_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, default=0)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class PriceInput(serializers.Serializer):
    supplier_id = serializers.IntegerField(min_value=1)
    sku_id = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0)
    effective_date = serializers.DateField(default=business_date)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default="")
    expected_version = serializers.IntegerField(min_value=0)

    def validate_effective_date(self, value):
        if value > business_date():
            raise serializers.ValidationError("本期不支持预约生效价格，请填写今天或更早的日期。")
        return value
