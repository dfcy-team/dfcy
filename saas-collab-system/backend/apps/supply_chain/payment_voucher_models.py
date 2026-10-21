"""Private, append-only files attached to an immutable settlement revision."""
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from .models import Record


class PaymentVoucher(Record):
    settlement_revision = models.ForeignKey(
        "supply_chain.SettlementRevision",
        on_delete=models.PROTECT,
        related_name="payment_vouchers",
    )
    file_name = models.CharField(max_length=200)
    media_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    idempotency_key = models.CharField(max_length=128)
    content = models.BinaryField()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "settlement_revision", "idempotency_key"],
                name="sc2_voucher_revision_key",
            ),
            models.CheckConstraint(condition=models.Q(byte_size__gt=0), name="sc2_voucher_size_positive"),
        ]
        indexes = [models.Index(fields=["tenant", "settlement_revision", "created_at"], name="sc2_voucher_revision_idx")]

    def clean(self):
        super().clean()
        if self.settlement_revision_id and self.settlement_revision.tenant_id != self.tenant_id:
            raise ValidationError("凭证和结算历史必须属于同一租户。")
        if self.media_type not in {"application/pdf", "image/jpeg", "image/png"}:
            raise ValidationError("仅支持 PDF、JPG、PNG 凭证。")
        if self.byte_size > 10 * 1024 * 1024 or len(self.content or b"") != self.byte_size:
            raise ValidationError("凭证大小无效或超过 10MB。")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("结算凭证不可修改，请上传新的凭证。")
        return super().save(*args, **kwargs)
