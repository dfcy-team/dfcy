from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class AttachmentFile(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="attachment_files")
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    file_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_files",
    )
    business_type = models.CharField(max_length=80, blank=True)
    business_id = models.CharField(max_length=100, blank=True)
    is_private = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "business_type", "business_id"], name="idx_attachment_business"),
        ]

    def __str__(self):
        return self.file_name
