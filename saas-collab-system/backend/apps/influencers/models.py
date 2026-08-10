from django.db import models

from apps.tenants.models import Tenant


class Influencer(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    class CooperationStatus(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        CONTACTED = "contacted", "Contacted"
        COOPERATING = "cooperating", "Cooperating"
        PAUSED = "paused", "Paused"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="influencers")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    platform = models.CharField(max_length=40)
    handle = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=80, blank=True)
    follower_count = models.PositiveBigIntegerField(default=0)
    contact_name = models.CharField(max_length=80, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_email = models.EmailField(blank=True)
    cooperation_status = models.CharField(max_length=20, choices=CooperationStatus.choices, default=CooperationStatus.PROSPECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_influencer_code_per_tenant")]
