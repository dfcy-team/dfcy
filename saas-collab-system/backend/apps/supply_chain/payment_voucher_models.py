"""Private, append-only files attached to an immutable settlement revision."""
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from .models import Record


class PaymentVoucher(Record):
    settlement_revision = models.ForeignKey(
        "supply_chain.SettlementRevision",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="payment_vouchers",
    )
    payment = models.ForeignKey("supply_chain.PaymentRecord", on_delete=models.PROTECT,
        null=True, blank=True, related_name="vouchers")
    file_name = models.CharField(max_length=200)
    media_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    idempotency_key = models.CharField(max_length=128)
    content = models.BinaryField(blank=True)
    content_storage_alias = models.CharField(max_length=80, null=True, blank=True)
    content_object_key = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=(models.Q(settlement_revision__isnull=False, payment__isnull=True) | models.Q(settlement_revision__isnull=True, payment__isnull=False)), name="sc2_voucher_one_parent"),
            models.UniqueConstraint(
                fields=["tenant", "settlement_revision", "idempotency_key"],
                name="sc2_voucher_revision_key",
            ),
            models.UniqueConstraint(fields=["tenant", "payment", "idempotency_key"], name="sc2_voucher_payment_key"),
            models.CheckConstraint(condition=models.Q(byte_size__gt=0), name="sc2_voucher_size_positive"),
        ]
        indexes = [models.Index(fields=["tenant", "settlement_revision", "created_at"], name="sc2_voucher_revision_idx")]

    def clean(self):
        super().clean()
        if self.settlement_revision_id and self.settlement_revision.tenant_id != self.tenant_id:
            raise ValidationError("凭证和结算历史必须属于同一租户。")
        if self.payment_id and self.payment.tenant_id != self.tenant_id:
            raise ValidationError("凭证和付款记录必须属于同一租户。")
        if self.media_type not in {"application/pdf", "image/jpeg", "image/png"}:
            raise ValidationError("仅支持 PDF、JPG、PNG 凭证。")
        from .payment_voucher_storage import VoucherStorageError, object_key, validate_content
        try:
            if self.content_storage_alias or self.content_object_key:
                parent_kind = "payment" if self.payment_id else "settlement_revision"
                expected = object_key(self.tenant_id, parent_kind,
                    self.payment_id or self.settlement_revision_id, self.idempotency_key, self.sha256)
                if (not self.content_storage_alias or len(self.content_storage_alias) > 80
                        or self.content_object_key != expected or self.content
                        or not 0 < self.byte_size <= 10 * 1024 * 1024):
                    raise VoucherStorageError("凭证存储引用无效。")
            else:
                validate_content(bytes(self.content or b""), self.byte_size, self.sha256)
        except VoucherStorageError as exc:
            raise ValidationError(str(exc)) from exc

    def read_content(self):
        from .payment_voucher_storage import read_content
        return read_content(self)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("结算凭证不可修改，请上传新的凭证。")
        return super().save(*args, **kwargs)
