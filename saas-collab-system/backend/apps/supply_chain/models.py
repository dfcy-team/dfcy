"""New canonical supply-chain aggregates; legacy records remain untouched.

Writes go through services, which own authorization, locking and event history.
No stock snapshot, payment, or external message is written by these models.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


_write_depth = ContextVar("supply_chain_write_depth", default=0)


@contextmanager
def domain_write():
    token = _write_depth.set(_write_depth.get() + 1)
    try:
        yield
    finally:
        _write_depth.reset(token)


class ProtectedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use the supply-chain action service.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use the supply-chain action service.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use the supply-chain action service.")

    def delete(self):
        raise ValidationError("Supply-chain history must be retained.")


class Record(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)
    objects = ProtectedQuerySet.as_manager()

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        for field in self._meta.fields:
            if field.is_relation and field.name != "tenant" and getattr(self, field.attname):
                related = getattr(self, field.name)
                if getattr(related, "tenant_id", self.tenant_id) != self.tenant_id:
                    raise ValidationError({field.name: "Related records must belong to the same tenant."})

    def save(self, *args, **kwargs):
        if not _write_depth.get():
            raise ValidationError("Use the supply-chain action service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Supply-chain history must be retained.")


class PurchaseOrder(Record):
    class Source(models.TextChoices):
        OPERATING = "operating", "运营订货单拆分"
        MANUAL = "manual", "采购直接创建"
        IMPORT = "import", "采购导入"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        CONFIRMED = "confirmed", "已下单"
        CANCELLED = "cancelled", "已作废"

    number = models.CharField(max_length=80)
    reference_number = models.CharField(max_length=120, blank=True)
    supplier = models.ForeignKey("masterdata.SupplierMaster", on_delete=models.PROTECT)
    country = models.ForeignKey("masterdata.CountrySiteMaster", on_delete=models.PROTECT)
    country_code_snapshot = models.CharField(max_length=8)
    source_kind = models.CharField(max_length=16, choices=Source.choices)
    import_batch_ref = models.CharField(max_length=128, blank=True)
    supplier_terms_snapshot = models.JSONField(default=dict, blank=True)
    order_date = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    creation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="sc2_po_number"),
            models.UniqueConstraint(fields=["tenant", "creation_key"], name="sc2_po_create_key"),
        ]
        ordering = ["-id"]


class PurchaseLine(Record):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    sku = models.ForeignKey("products.ProductSKU", on_delete=models.PROTECT)
    sku_code_snapshot = models.CharField(max_length=80)
    product_name_snapshot = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField()
    product_reference_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    supplier_reference_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    import_row_number = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_number"], name="sc2_po_line_number"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sc2_po_qty_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__isnull=True) | models.Q(unit_price__gte=0), name="sc2_po_price_nonnegative"),
        ]


class OperatingAllocation(Record):
    """Read-only upstream identity, never a copy of an operating-order aggregate."""
    purchase_line = models.ForeignKey(PurchaseLine, on_delete=models.PROTECT, related_name="operating_sources")
    source_system = models.CharField(max_length=80)
    source_order_id = models.CharField(max_length=128)
    source_line_id = models.CharField(max_length=128)
    allocated_quantity = models.PositiveIntegerField()
    operating_line = models.ForeignKey('sales_management.OperatingOrderLine', on_delete=models.PROTECT,
        null=True, blank=True, related_name='purchase_allocations')

    class Meta:
        indexes = [models.Index(fields=['tenant', 'source_system', 'source_line_id'], name='sc2_operating_source_idx')]
        constraints = [
            models.UniqueConstraint(fields=["purchase_line", "source_system", "source_order_id", "source_line_id"], name="sc2_operating_source"),
            models.CheckConstraint(condition=models.Q(allocated_quantity__gt=0), name="sc2_source_qty_positive"),
        ]

    def clean(self):
        super().clean()
        if self.operating_line_id and self.purchase_line_id:
            source, target = self.operating_line, self.purchase_line
            if (source.sku_id != target.sku_id or source.order.country_code_snapshot != target.order.country_code_snapshot
                    or self.source_system != 'sales_management' or self.source_order_id != str(source.order_id)
                    or self.source_line_id != str(source.pk) or target.order.source_kind != 'operating'):
                raise ValidationError('运营来源必须与采购商品、国家和真实来源标识一致。')


class SupplierShipment(Record):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        SUBMITTED = "submitted", "已提交"
        CANCELLED = "cancelled", "已作废"

    class EntryMode(models.TextChoices):
        SUPPLIER = "supplier", "供应商录入"
        PROCUREMENT = "procurement", "采购代录"

    class DeliveryMode(models.TextChoices):
        COLLECTION_CENTER = "collection_center", "送集货中心"
        FACTORY_LOADING = "factory_loading", "货柜上门装载"

    number = models.CharField(max_length=80)
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="supplier_shipments")
    shipment_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    entry_mode = models.CharField(max_length=16, choices=EntryMode.choices)
    delivery_mode = models.CharField(max_length=24, choices=DeliveryMode.choices, default=DeliveryMode.COLLECTION_CENTER)
    loading_address_snapshot = models.TextField(blank=True)
    collection_arrived = models.BooleanField(default=False)
    collection_arrived_at = models.DateTimeField(null=True, blank=True)
    collection_arrived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="sc2_collection_arrivals")
    notes = models.TextField(blank=True)
    creation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="sc2_shipment_number"),
            models.UniqueConstraint(fields=["tenant", "creation_key"], name="sc2_shipment_create_key"),
            models.CheckConstraint(condition=models.Q(collection_arrived=False, collection_arrived_at__isnull=True, collection_arrived_by__isnull=True) | models.Q(collection_arrived=True, collection_arrived_at__isnull=False, collection_arrived_by__isnull=False), name="sc2_collection_arrival_valid"),
            models.CheckConstraint(condition=~models.Q(delivery_mode="factory_loading") | models.Q(collection_arrived=False), name="sc2_factory_no_collection_arrival"),
        ]
        ordering = ["-id"]


class ShipmentLine(Record):
    class ExceptionType(models.TextChoices):
        NONE = "none", "正常"
        EXCESS = "excess", "超采购数量"
        ADDITIONAL = "additional", "采购单外商品"

    shipment = models.ForeignKey(SupplierShipment, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    sku = models.ForeignKey("products.ProductSKU", on_delete=models.PROTECT)
    purchase_line = models.ForeignKey(PurchaseLine, on_delete=models.PROTECT, null=True, blank=True, related_name="shipment_lines")
    sku_code_snapshot = models.CharField(max_length=80)
    product_name_snapshot = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField()
    purchase_price_snapshot = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    exception_type = models.CharField(max_length=16, choices=ExceptionType.choices, default=ExceptionType.NONE)
    excess_quantity = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["line_number"]
        constraints = [
            models.UniqueConstraint(fields=["shipment", "line_number"], name="sc2_shipment_line_number"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sc2_shipped_qty_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__isnull=True) | models.Q(unit_price__gte=0), name="sc2_shipped_price_valid"),
        ]

    def clean(self):
        super().clean()
        if self.purchase_line_id and (self.purchase_line.order_id != self.shipment.order_id or self.purchase_line.sku_id != self.sku_id):
            raise ValidationError("Shipment source must match its purchase order and SKU.")
        if self.exception_type == self.ExceptionType.ADDITIONAL and self.purchase_line_id:
            raise ValidationError("An additional SKU cannot reference a purchase line.")
        if not self.purchase_line_id and self.exception_type != self.ExceptionType.ADDITIONAL:
            raise ValidationError("A shipment line without a purchase source must be marked additional.")


class BoxInfoAttachment(Record):
    shipment = models.ForeignKey(SupplierShipment, on_delete=models.PROTECT, related_name="box_attachments")
    # Private file metadata only; never expose file_path via supplier serializers.
    file = models.ForeignKey("files.AttachmentFile", on_delete=models.PROTECT)
    sha256 = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    is_active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.file_id and (not self.file.is_private or self.file.business_type != "sc2_supplier_shipment" or self.file.business_id != str(self.shipment_id)):
            raise ValidationError("Box information must be a private file bound to this shipment.")


class BoxFileContent(Record):
    """Bounded private bytes, committed atomically with metadata and audit.

    No MEDIA/static path or anonymous object URL exists. Object storage may
    replace this adapter later without changing the authorized HTTP contract.
    """
    attachment = models.OneToOneField(BoxInfoAttachment, on_delete=models.PROTECT, related_name="content")
    body = models.BinaryField()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Uploaded box files are immutable; upload a new version.")
        return super().save(*args, **kwargs)


class SupplierContactAccount(Record):
    supplier = models.ForeignKey("masterdata.SupplierMaster", on_delete=models.PROTECT, related_name="sc2_contact_accounts")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sc2_contact_account")

    def clean(self):
        super().clean()
        if self.user_id and self.user.user_type != "external":
            raise ValidationError("Supplier contact must be an external account.")


class FreightCompany(Record):
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    contact = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    province = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    shipping_marks = models.TextField(blank=True)
    fee_per_cbm = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="sc2_freight_code"),
            models.CheckConstraint(condition=models.Q(tax_percent__gte=0, tax_percent__lte=100), name="sc2_freight_tax_range"),
            models.CheckConstraint(condition=models.Q(fee_per_cbm__isnull=True) | models.Q(fee_per_cbm__gte=0), name="sc2_freight_fee_valid"),
        ]


class DispatchBatch(Record):
    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        CANCELLED = "cancelled", "已取消"

    class Stage(models.TextChoices):
        UNMARKED = "unmarked", "未标记"
        DEPARTED = "departed", "开船"
        ARRIVED_PORT = "arrived_port", "到港"
        ARRIVED_WAREHOUSE = "arrived_warehouse", "到仓"

    number = models.CharField(max_length=80)
    country = models.ForeignKey("masterdata.CountrySiteMaster", on_delete=models.PROTECT)
    country_code_snapshot = models.CharField(max_length=8)
    freight_company = models.ForeignKey(FreightCompany, on_delete=models.PROTECT)
    freight_number = models.CharField(max_length=120)
    shipping_marks_snapshot = models.TextField(blank=True)
    fee_per_cbm_snapshot = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    tax_percent_snapshot = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    freight_channel = models.ForeignKey('supply_chain.FreightChannel', on_delete=models.PROTECT, null=True, blank=True)
    freight_quote = models.ForeignKey('supply_chain.FreightQuote', on_delete=models.PROTECT, null=True, blank=True)
    freight_quote_snapshot = models.JSONField(default=dict, blank=True)
    container_number = models.CharField(max_length=128, blank=True)
    container_count = models.PositiveSmallIntegerField(default=1)
    planned_warehouse = models.ForeignKey('masterdata.WarehouseMaster', on_delete=models.PROTECT, null=True, blank=True, related_name='planned_supply_batches')
    expected_warehouse_date = models.DateField(null=True, blank=True)
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.UNMARKED)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    departed_at = models.DateTimeField(null=True, blank=True)
    arrived_port_at = models.DateTimeField(null=True, blank=True)
    arrived_warehouse_at = models.DateTimeField(null=True, blank=True)
    billed_cbm = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    notes = models.TextField(blank=True)
    creation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="sc2_dispatch_number"),
            models.UniqueConstraint(fields=["tenant", "creation_key"], name="sc2_dispatch_create_key"),
            models.CheckConstraint(condition=models.Q(status="active") | models.Q(
                status="cancelled", stage="unmarked", departed_at__isnull=True,
                arrived_port_at__isnull=True, arrived_warehouse_at__isnull=True), name="sc2_cancel_before_departure"),
        ]
        ordering = ["-id"]


class DispatchMembership(Record):
    batch = models.ForeignKey(DispatchBatch, on_delete=models.PROTECT, related_name="memberships")
    shipment = models.ForeignKey(SupplierShipment, on_delete=models.PROTECT, related_name="dispatch_memberships")
    # NULL releases historical membership; allocation quantities enforce capacity.
    active_guard = models.BooleanField(null=True, default=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "shipment", "active_guard"], name="sc2_batch_active_shipment"),
            models.CheckConstraint(condition=models.Q(active_guard=True) | models.Q(active_guard__isnull=True), name="sc2_dispatch_guard_valid"),
        ]

    def clean(self):
        super().clean()
        if self.shipment_id and self.batch_id and self.shipment.order.country_code_snapshot != self.batch.country_code_snapshot:
            raise ValidationError("A dispatch batch cannot mix destination countries.")


class DispatchAllocation(Record):
    membership = models.ForeignKey(DispatchMembership, on_delete=models.PROTECT, related_name="allocations")
    shipment_line = models.ForeignKey(ShipmentLine, on_delete=models.PROTECT, related_name="dispatch_allocations")
    quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "shipment_line"], name="sc2_dispatch_line_unique"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sc2_dispatch_quantity_positive"),
        ]

    def clean(self):
        super().clean()
        if self.membership_id and self.shipment_line_id:
            if self.membership.shipment_id != self.shipment_line.shipment_id or self.quantity > self.shipment_line.quantity:
                raise ValidationError("集货商品须属于所选发货单，数量不能超过发货量。")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("集货数量历史不可覆盖，请通过调整批次生成新分配。")
        return super().save(*args, **kwargs)


class InboundOrder(Record):
    class Status(models.TextChoices):
        DRAFT = "draft", "待核对"
        CONFIRMED = "confirmed", "已入库"

    number = models.CharField(max_length=80)
    batch = models.OneToOneField(DispatchBatch, on_delete=models.PROTECT, related_name="inbound_order")
    warehouse = models.ForeignKey("masterdata.WarehouseMaster", on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    clearance_cbm = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    stock_receipt_ref = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="sc2_confirmed_inbounds")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="sc2_inbound_number")]
        ordering = ["-id"]

    def clean(self):
        super().clean()
        if self.batch_id and self.warehouse_id and self.warehouse.country_code.upper() != self.batch.country_code_snapshot:
            raise ValidationError("Select a warehouse in the batch destination country.")
        if self.status == self.Status.CONFIRMED and not self.stock_receipt_ref:
            raise ValidationError("Confirmed inbound requires an authoritative stock receipt reference.")


class InboundLine(Record):
    inbound = models.ForeignKey(InboundOrder, on_delete=models.PROTECT, related_name="lines")
    shipment_line = models.ForeignKey(ShipmentLine, on_delete=models.PROTECT, related_name="inbound_lines")
    expected_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField(null=True, blank=True)
    difference_note = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["inbound", "shipment_line"], name="sc2_inbound_source_line")]

    def clean(self):
        super().clean()
        if self.inbound_id and self.shipment_line_id and not DispatchAllocation.objects.filter(membership__batch_id=self.inbound.batch_id, shipment_line_id=self.shipment_line_id, membership__active_guard=True, quantity=self.expected_quantity).exists():
            raise ValidationError("Inbound source line must belong to the dispatch batch.")


class InternalStockReceipt(Record):
    """Authoritative local inbound fact; not an external WMS stock balance."""
    inbound = models.OneToOneField(InboundOrder, on_delete=models.PROTECT, related_name="stock_receipt")
    warehouse = models.ForeignKey("masterdata.WarehouseMaster", on_delete=models.PROTECT)
    receipt_ref = models.CharField(max_length=128)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "receipt_ref"], name="sc2_stock_receipt_ref")]

    def clean(self):
        super().clean()
        if self.inbound_id and self.warehouse_id != self.inbound.warehouse_id:
            raise ValidationError("Receipt warehouse must match the inbound order.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock receipt facts are append-only.")
        return super().save(*args, **kwargs)


class InternalStockReceiptLine(Record):
    receipt = models.ForeignKey(InternalStockReceipt, on_delete=models.PROTECT, related_name="lines")
    inbound_line = models.OneToOneField(InboundLine, on_delete=models.PROTECT, related_name="stock_entry")
    sku = models.ForeignKey("products.ProductSKU", on_delete=models.PROTECT)
    sku_code_snapshot = models.CharField(max_length=80)
    received_quantity = models.PositiveIntegerField()

    def clean(self):
        super().clean()
        if self.inbound_line_id and (self.inbound_line.inbound_id != self.receipt.inbound_id
                or self.sku_id != self.inbound_line.shipment_line.sku_id
                or self.received_quantity != self.inbound_line.received_quantity):
            raise ValidationError("Stock entry must match its checked inbound source.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock receipt entries are append-only.")
        return super().save(*args, **kwargs)


class BusinessEvent(Record):
    aggregate_type = models.CharField(max_length=40)
    aggregate_id = models.PositiveBigIntegerField()
    aggregate_version = models.PositiveIntegerField()
    action = models.CharField(max_length=60)
    request_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "aggregate_type", "aggregate_id", "action", "request_key"], name="sc2_event_request_key")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Business events are append-only.")
        return super().save(*args, **kwargs)


# Keep numbering records in their own module while registering them with Django.
from .numbering_models import DocumentNumberCounter, DocumentNumberRule  # noqa: E402,F401


class NotificationOutbox(Record):
    event = models.OneToOneField(BusinessEvent, on_delete=models.PROTECT)
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT)
    order_version = models.PositiveIntegerField()
    notification_type = models.CharField(max_length=40, default="purchase_confirmed")
    status = models.CharField(max_length=24, default="blocked")
    blocked_reason = models.CharField(max_length=120, default="channel_not_verified", blank=True)
    binding = models.ForeignKey('supply_chain.SupplierGroupBinding', on_delete=models.PROTECT, null=True, blank=True)
    target_snapshot = models.JSONField(default=dict, blank=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    total_quantity = models.PositiveIntegerField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    summary = models.TextField(blank=True)
    supplier_url = models.URLField(max_length=2048, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "order_version", "notification_type"], name="sc2_order_notification_version")]

    def clean(self):
        super().clean()
        if self.event_id and (self.event.aggregate_type != "purchaseorder" or self.event.aggregate_id != self.order_id or self.event.aggregate_version != self.order_version or self.event.action != "confirmed"):
            raise ValidationError("Outbox must reference this purchase confirmation event and version.")


class SupplierProductPrice(Record):
    supplier = models.ForeignKey("masterdata.SupplierMaster", on_delete=models.PROTECT)
    sku = models.ForeignKey("products.ProductSKU", on_delete=models.PROTECT)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    effective_date = models.DateField()
    source_kind = models.CharField(max_length=20, choices=[("manual", "人工维护"), ("purchase_order", "采购单保存")])
    source_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT)
    source_order_version = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "supplier", "sku"], name="sc2_supplier_sku_price"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="sc2_supplier_price_nonnegative"),
        ]


class SupplierPriceHistory(Record):
    price = models.ForeignKey(SupplierProductPrice, on_delete=models.PROTECT, related_name="history")
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    effective_date = models.DateField()
    source_kind = models.CharField(max_length=20)
    source_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT)
    source_order_version = models.PositiveIntegerField(null=True, blank=True)
    applied_to_current = models.BooleanField()
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Price history is append-only.")
        return super().save(*args, **kwargs)


class PurchaseImport(Record):
    filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    file_content = models.BinaryField()
    creation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    preview = models.JSONField(default=dict)
    committed_at = models.DateTimeField(null=True, blank=True)
    order_ids = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "creation_key"], name="sc2_import_create_key")]


# Loaded after Record and the document aggregates to avoid a circular base import.
from .cost_models import (FeeRecord, FeeRevision, CostVersion, CostEntry, CostAdjustment,
                          SettlementRecord, SettlementRevision)  # noqa: E402,F401
from .notification_models import (NotificationChannel, SupplierGroupBinding, NotificationPart, NotificationAttempt,
    NotificationEvidence, NotificationReceipt, NotificationDownload, NotificationThrottle)  # noqa: E402,F401
from .freight_models import FreightChannel, FreightQuote  # noqa: E402,F401
from .wms_models import WmsReceiptAllocation  # noqa: E402,F401
from .payment_voucher_models import PaymentVoucher  # noqa: E402,F401
