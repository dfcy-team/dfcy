"""Durable write-attempt fence; stores hashes/status, never business payloads."""
from django.conf import settings
from django.db import models


class WarehouseApiAttempt(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    authorization = models.ForeignKey("integrations.WarehouseAuthorization", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=60)
    key_hash = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default="running", choices=[
        ("running", "执行中"), ("succeeded", "成功"), ("rejected", "仓库拒绝"), ("unknown", "结果待核实")])
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "key_hash"], name="uniq_warehouse_api_attempt")]
        indexes = [models.Index(fields=["tenant", "authorization", "created_at"], name="idx_wh_api_attempt")]
