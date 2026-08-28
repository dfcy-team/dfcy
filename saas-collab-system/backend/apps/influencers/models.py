from decimal import Decimal
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import OuterRef, Q
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


SUPPORTED_CURRENCY_CHOICES = (
    ("CNY", "CNY"),
    ("PHP", "PHP"),
    ("MYR", "MYR"),
    ("THB", "THB"),
    ("USD", "USD"),
)


def normalize_tiktok_username(value):
    return str(value or "").strip().lstrip("@").strip().lower()


TIKTOK_USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{1,255}$")


def is_valid_tiktok_username(value):
    return bool(TIKTOK_USERNAME_PATTERN.fullmatch(normalize_tiktok_username(value)))


def influencer_identity_key(*, influencer_id, platform, handle):
    canonical_handle = normalize_tiktok_username(handle)
    if str(platform or "").strip().lower() == "tiktok" and canonical_handle:
        return ("tiktok", canonical_handle)
    return ("profile", influencer_id)


class ProtectedInfluencerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Influencer profiles must be updated through audited services.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Bulk create is disabled for influencer profiles.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Bulk update is disabled for influencer profiles.")


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
    handle = models.CharField(max_length=255, blank=True, db_comment="TikTok用户名")
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
    objects = ProtectedInfluencerQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_influencer_code_per_tenant")]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        update_fields = set(update_fields) if update_fields is not None else None
        writes_identity = update_fields is None or bool({"handle", "platform"} & update_fields)

        def save_identity():
            if self.pk:
                persisted = type(self).objects.filter(pk=self.pk).values(
                    "tenant_id", "handle", "platform"
                ).first()
                if persisted is not None and (
                    persisted["handle"] != self.handle or persisted["platform"] != self.platform
                ):
                    lock_influencer_identity_change(
                        self,
                        platform=self.platform,
                        handle=self.handle,
                    )
            if str(self.platform or "").lower() == "tiktok":
                self.handle = normalize_tiktok_username(self.handle)
                if self.handle and not is_valid_tiktok_username(self.handle):
                    raise ValidationError({
                        "handle": "TikTok username may contain only letters, numbers, periods, and underscores.",
                    })
                if update_fields is not None:
                    kwargs["update_fields"] = update_fields | {"handle"}
            return super(Influencer, self).save(*args, **kwargs)

        if writes_identity:
            with transaction.atomic():
                return save_identity()
        return super().save(*args, **kwargs)


class TenantValidatedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Tenant-owned influencer records must be updated through validated services.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Bulk create is disabled for tenant-owned influencer records.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Bulk update is disabled for tenant-owned influencer records.")


class TenantValidatedModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    objects = TenantValidatedQuerySet.as_manager()

    class Meta:
        abstract = True

    tenant_relation_fields = ()

    def clean(self):
        super().clean()
        for field_name in self.tenant_relation_fields:
            related = getattr(self, field_name, None)
            if related is not None and related.tenant_id != self.tenant_id:
                raise ValidationError({field_name: "Related object must belong to the same tenant."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StateMachineTenantModel(TenantValidatedModel):
    """Prevent ordinary ORM saves from changing audited workflow state."""

    class Meta:
        abstract = True

    protected_state_fields = ()
    initial_state_values = {}

    def _assert_state_fields_unchanged(self):
        if self._state.adding or not self.pk:
            invalid = {
                field: "Workflow records must be created in their initial state."
                for field, expected in self.initial_state_values.items()
                if getattr(self, field) != expected
            }
            if invalid:
                raise ValidationError(invalid)
            return
        persisted = type(self).objects.filter(pk=self.pk).values(*self.protected_state_fields).first()
        if persisted is None:
            return
        changed = [field for field in self.protected_state_fields if getattr(self, field) != persisted[field]]
        if changed:
            raise ValidationError({field: "Use the audited state-machine service." for field in changed})

    def save(self, *args, **kwargs):
        self._assert_state_fields_unchanged()
        return super().save(*args, **kwargs)

    def save_base(self, *args, **kwargs):
        self._assert_state_fields_unchanged()
        return super().save_base(*args, **kwargs)


class InfluencerRestriction(TenantValidatedModel):
    influencer = models.ForeignKey(Influencer, on_delete=models.CASCADE, related_name="restrictions")
    is_blacklisted = models.BooleanField(default=True)
    reason = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="influencer_restrictions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer", "created_by")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "influencer"], name="uniq_influencer_restriction")]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Influencer.objects.select_for_update().get(pk=self.influencer_id, tenant_id=self.tenant_id)
            return super().save(*args, **kwargs)


def influencer_identity_queryset(
    influencer,
    *,
    platform=None,
    handle=None,
    for_update=False,
):
    """Return the tenant-scoped identity group, always retaining the current profile."""
    if not influencer.pk:
        return Influencer.objects.none()
    platform = influencer.platform if platform is None else platform
    handle = influencer.handle if handle is None else handle
    canonical_handle = normalize_tiktok_username(handle)
    identity_filter = Q(pk=influencer.pk)
    if str(platform or "").lower() == "tiktok" and canonical_handle:
        identity_filter |= Q(
            platform__iexact="TikTok",
            handle__iexact=canonical_handle,
        )
    queryset = Influencer.objects.filter(
        tenant_id=influencer.tenant_id,
    ).filter(identity_filter).order_by("pk")
    return queryset.select_for_update() if for_update else queryset


def lock_influencer_identity_change(influencer, *, platform, handle):
    """Lock and validate the current and prospective TikTok identity groups."""
    persisted = Influencer.objects.filter(
        tenant_id=influencer.tenant_id,
        pk=influencer.pk,
    ).values("platform", "handle").first()
    identity_ids = set(
        influencer_identity_queryset(
            influencer,
            platform=persisted["platform"] if persisted else influencer.platform,
            handle=persisted["handle"] if persisted else influencer.handle,
        ).values_list("pk", flat=True)
    )
    canonical_handle = normalize_tiktok_username(handle)
    if str(platform or "").lower() == "tiktok" and canonical_handle:
        identity_ids.update(
            Influencer.objects.filter(
                tenant_id=influencer.tenant_id,
                platform__iexact="TikTok",
                handle__iexact=canonical_handle,
            ).values_list("pk", flat=True)
        )
    identity_ids.add(influencer.pk)
    locked = list(
        Influencer.objects.select_for_update()
        .filter(tenant_id=influencer.tenant_id, pk__in=sorted(identity_ids))
        .order_by("pk")
    )
    if InfluencerRestriction.objects.filter(
        tenant_id=influencer.tenant_id,
        influencer_id__in=identity_ids,
        is_blacklisted=True,
    ).exists():
        raise ValidationError({
            "handle": "Blacklisted influencer identities cannot change handle or platform.",
        })
    return next(item for item in locked if item.pk == influencer.pk)


def influencer_has_active_restriction(
    influencer,
    *,
    platform=None,
    handle=None,
    for_update=False,
):
    identity_queryset = influencer_identity_queryset(
        influencer,
        platform=platform,
        handle=handle,
        for_update=for_update,
    )
    identity_ids = identity_queryset.values_list("pk", flat=True)
    if for_update:
        identity_ids = list(identity_ids)
    return InfluencerRestriction.objects.filter(
        tenant_id=influencer.tenant_id,
        influencer_id__in=identity_ids,
        is_blacklisted=True,
    ).exists()


def _assert_influencer_identity_change_allowed(influencer, persisted):
    if influencer_has_active_restriction(
        influencer,
        platform=persisted["platform"],
        handle=persisted["handle"],
        for_update=True,
    ):
        raise ValidationError({
            "handle": "Blacklisted influencer identities cannot change handle or platform.",
        })


def active_influencer_restriction_subquery(tenant):
    tenant_id = getattr(tenant, "pk", tenant)
    identity_match = (
        Q(influencer__tenant_id=tenant_id)
        & Q(influencer__platform__iexact="TikTok")
        & Q(influencer__platform__iexact=OuterRef("platform"))
        & Q(influencer__handle__iexact=OuterRef("handle"))
        & Q(influencer__handle__gt="")
    )
    return InfluencerRestriction.objects.filter(
        tenant_id=tenant_id,
        is_blacklisted=True,
    ).filter(
        Q(influencer_id=OuterRef("pk")) | identity_match
    )


class OutreachTask(StateMachineTenantModel):
    protected_state_fields = (
        "status",
        "version",
        "started_at",
        "finalized_at",
        "dispatch_time",
        "outreach_at",
        "is_deleted",
        "deleted_at",
    )
    initial_state_values = {
        "status": "pending",
        "version": 1,
        "started_at": None,
        "finalized_at": None,
        "outreach_at": None,
        "is_deleted": False,
        "deleted_at": None,
    }

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    task_no = models.CharField(max_length=80)
    task_name = models.CharField(max_length=160, blank=True)
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outreach_tasks",
    )
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_outreach_tasks")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, null=True, blank=True, related_name="influencer_outreach_tasks")
    external_product_id = models.CharField(max_length=120, blank=True)
    sku_prefix = models.CharField(max_length=120, blank=True)
    product_name_snapshot = models.CharField(max_length=240, blank=True)
    product_match_status = models.CharField(max_length=20, default="pending")
    product_match_source = models.CharField(max_length=40, blank=True)
    product_matched_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=20, default="normal")
    target_count = models.PositiveIntegerField(default=0)
    dispatcher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="dispatched_outreach_tasks")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_outreach_tasks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    dispatch_time = models.DateTimeField(default=timezone.now)
    outreach_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=40, default="manual")
    external_id = models.CharField(max_length=160, blank=True, null=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer", "store", "spu", "dispatcher", "owner")

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "task_no"], name="uniq_outreach_task_no"),
            models.UniqueConstraint(fields=["tenant", "source", "external_id"], name="uniq_outreach_external"),
        ]
        indexes = [models.Index(fields=["tenant", "owner", "status"], name="idx_outreach_owner_status")]

    @property
    def linked_count(self):
        if not self.pk:
            return 0
        prefetched_targets = getattr(self, "_active_targets", None)
        if prefetched_targets is not None:
            rows = (
                (target.influencer_id, target.influencer.platform, target.influencer.handle)
                for target in prefetched_targets
            )
        else:
            rows = self.targets.filter(
                tenant_id=self.tenant_id,
                is_deleted=False,
            ).values_list(
                "influencer_id",
                "influencer__platform",
                "influencer__handle",
            )
        return len({
            influencer_identity_key(
                influencer_id=influencer_id,
                platform=platform,
                handle=handle,
            )
            for influencer_id, platform, handle in rows
        })


class OutreachTarget(StateMachineTenantModel):
    """A tenant-scoped influencer link owned by one outreach task."""

    protected_state_fields = (
        "first_linked_at",
        "outreach_result",
        "version",
        "is_deleted",
        "deleted_at",
    )
    initial_state_values = {
        "outreach_result": "pending",
        "version": 1,
        "is_deleted": False,
        "deleted_at": None,
    }

    class OutreachResult(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        REJECTED = "rejected", "Rejected"
        NO_RESPONSE = "no_response", "No response"
        BLOCKED = "blocked", "Blocked"

    task = models.ForeignKey(OutreachTask, on_delete=models.PROTECT, related_name="targets")
    influencer = models.ForeignKey(Influencer, on_delete=models.PROTECT, related_name="outreach_targets")
    first_linked_at = models.DateTimeField(default=timezone.now)
    outreach_result = models.CharField(
        max_length=20, choices=OutreachResult.choices, default=OutreachResult.PENDING
    )
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("task", "influencer")

    class Meta:
        ordering = ["tenant_id", "task_id", "first_linked_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "task", "influencer"],
                name="uniq_outreach_target_relation",
            )
        ]
        indexes = [models.Index(fields=["tenant", "task", "is_deleted"], name="idx_target_task_active")]

    def clean(self):
        super().clean()
        if self._state.adding and self.task_id:
            task = OutreachTask.objects.filter(pk=self.task_id).values(
                "is_deleted", "status"
            ).first()
            if task is not None and task["is_deleted"]:
                raise ValidationError({"task": "Deleted outreach tasks cannot receive targets."})
            if task is not None and task["status"] in {
                OutreachTask.Status.COMPLETED,
                OutreachTask.Status.CANCELLED,
            }:
                raise ValidationError({"task": "Terminal outreach tasks cannot receive targets."})
        if self.is_deleted and self.deleted_at is None:
            raise ValidationError({"deleted_at": "Deleted outreach targets require deleted_at."})
        if not self.is_deleted and self.deleted_at is not None:
            raise ValidationError({"deleted_at": "Active outreach targets cannot have deleted_at."})
        if self.task_id and not self._state.adding:
            task_status = OutreachTask.objects.filter(pk=self.task_id).values_list(
                "status", flat=True
            ).first()
            if task_status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}:
                raise ValidationError({"task": "Terminal outreach tasks cannot change targets."})


class SampleFulfillment(StateMachineTenantModel):
    protected_state_fields = (
        "status",
        "version",
        "finalized_at",
        "sample_sent_at",
        "shipped_at",
        "is_deleted",
        "deleted_at",
        "deleted_by_id",
    )
    initial_state_values = {
        "status": "pending",
        "version": 1,
        "finalized_at": None,
        "shipped_at": None,
        "is_deleted": False,
        "deleted_at": None,
        "deleted_by_id": None,
    }

    LINK_TYPE_CHOICES = (
        ("DRJL", "BD建联"),
        ("YYJL", "运营建联"),
        ("PKDJ", "品库达人"),
        ("ZBDR", "直播达人"),
        ("TKOne", "TikTokOne建联"),
    )

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        PUBLISHED = "published", "Published"
        LIVE_CREATOR = "live_creator", "Live creator"
        OVERDUE = "overdue", "Overdue"
        BLACKLISTED = "blacklisted", "Blacklisted"

    fulfillment_no = models.CharField(max_length=80)
    request_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    outreach_task = models.ForeignKey(
        OutreachTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sample_fulfillments",
    )
    outreach_target = models.ForeignKey(
        OutreachTarget,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sample_fulfillments",
    )
    influencer = models.ForeignKey(Influencer, on_delete=models.PROTECT, related_name="sample_fulfillments")
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_sample_fulfillments")
    product_name_snapshot = models.CharField(max_length=240, blank=True)
    external_product_id = models.CharField(max_length=120, blank=True)
    sample_order_no = models.CharField(max_length=120, blank=True)
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES, default="DRJL")
    quick_tags = models.JSONField(blank=True, default=list)
    sample_sent_at = models.DateTimeField(default=timezone.now)
    shipped_at = models.DateTimeField(null=True, blank=True)
    video_deadline_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_sample_fulfillments")
    source = models.CharField(max_length=40, default="manual")
    external_id = models.CharField(max_length=160, blank=True, null=True)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    sku_quantity = models.PositiveIntegerField(default=0)
    sales_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    calculated_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    pricing_status = models.CharField(max_length=20, default="pending")
    priced_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deleted_sample_fulfillments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = (
        "outreach_task",
        "outreach_target",
        "influencer",
        "store",
        "owner",
        "deleted_by",
    )

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fulfillment_no"], name="uniq_sample_fulfillment_no"),
            models.UniqueConstraint(fields=["tenant", "request_key"], name="uniq_sample_request_key"),
            models.UniqueConstraint(fields=["tenant", "source", "external_id"], name="uniq_sample_external"),
        ]
        indexes = [
            models.Index(fields=["tenant", "owner", "status"], name="idx_sample_owner_status"),
            models.Index(
                fields=["tenant", "is_deleted", "video_deadline_at"],
                name="idx_sample_deadline",
            ),
        ]

    def clean(self):
        super().clean()
        if self.link_type not in dict(self.LINK_TYPE_CHOICES):
            raise ValidationError({"link_type": "Unsupported link type."})
        if not isinstance(self.quick_tags, list) or any(
            not isinstance(tag, str) or not tag.strip() for tag in self.quick_tags
        ):
            raise ValidationError({"quick_tags": "Quick tags must be a list of non-empty strings."})
        if self.is_deleted and self.deleted_at is None:
            raise ValidationError({"deleted_at": "Deleted sample fulfillments require deleted_at."})
        if not self.is_deleted and (self.deleted_at is not None or self.deleted_by_id is not None):
            raise ValidationError({"deleted_at": "Active sample fulfillments cannot have deletion metadata."})
        if not self.influencer_id:
            raise ValidationError({"influencer": "Influencer is required for sample fulfillments."})
        if not self.outreach_task_id:
            return
        task = OutreachTask.objects.filter(pk=self.outreach_task_id).values(
            "tenant_id", "influencer_id", "store_id", "owner_id", "external_product_id",
            "is_deleted", "status"
        ).first()
        if task is None:
            raise ValidationError({"outreach_task": "Outreach task does not exist."})
        if task["tenant_id"] != self.tenant_id:
            raise ValidationError({"outreach_task": "Outreach task must belong to the same tenant."})
        if task["is_deleted"] and self._state.adding:
            raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive samples."})
        if task["status"] in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED} and self._state.adding:
            raise ValidationError({"outreach_task": "Terminal outreach tasks cannot receive samples."})
        if self.store_id and task["store_id"] != self.store_id:
            raise ValidationError({"store": "Store must match the outreach task."})
        if self.owner_id and task["owner_id"] != self.owner_id:
            raise ValidationError({"owner": "Owner must match the outreach task."})
        if not self.outreach_target_id and task["influencer_id"] and task["influencer_id"] != self.influencer_id:
            raise ValidationError({"influencer": "Influencer must match the outreach task."})
        if task["external_product_id"] and self.external_product_id != task["external_product_id"]:
            raise ValidationError({"external_product_id": "Product must match the outreach task."})
        if self.outreach_target_id:
            target = OutreachTarget.objects.filter(pk=self.outreach_target_id).values(
                "tenant_id", "task_id", "influencer_id", "is_deleted"
            ).first()
            if target is None or target["tenant_id"] != self.tenant_id:
                raise ValidationError({"outreach_target": "Outreach target must belong to the same tenant."})
            if target["task_id"] != self.outreach_task_id:
                raise ValidationError({"outreach_target": "Outreach target must belong to the outreach task."})
            if target["influencer_id"] != self.influencer_id:
                raise ValidationError({"influencer": "Influencer must match the outreach target."})
            if target["is_deleted"] and self._state.adding:
                raise ValidationError({"outreach_target": "Deleted outreach targets cannot receive samples."})


class SampleItem(TenantValidatedModel):
    fulfillment = models.ForeignKey(SampleFulfillment, on_delete=models.CASCADE, related_name="items")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, null=True, blank=True, related_name="sample_items")
    external_product_id = models.CharField(max_length=120, blank=True)
    site_code = models.CharField(max_length=16)
    requested_sku = models.CharField(max_length=120, null=True, blank=True)
    product_name = models.CharField(max_length=240, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=8, blank=True)
    price_match_status = models.CharField(max_length=20, default="not_imported")
    normalized_sku = models.CharField(max_length=160, blank=True)
    matched_sku_code = models.CharField(max_length=80, blank=True)
    matched_legacy_sku_code = models.CharField(max_length=160, blank=True)
    sales_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cost_match_status = models.CharField(max_length=20, default="pending")
    price_source = models.CharField(max_length=40, blank=True)
    cost_source = models.CharField(max_length=40, blank=True)
    price_snapshot_at = models.DateTimeField(null=True, blank=True)
    cost_snapshot_at = models.DateTimeField(null=True, blank=True)
    match_notes = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("fulfillment", "sku")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "fulfillment", "requested_sku"], name="uniq_sample_item_requested_sku")]

    def clean(self):
        super().clean()
        if self.requested_sku is not None:
            self.requested_sku = self.requested_sku.strip() or None


class FulfillmentStatusEvent(TenantValidatedModel):
    fulfillment = models.ForeignKey(SampleFulfillment, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sample_status_events")
    reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("fulfillment", "actor")

    class Meta:
        ordering = ["created_at", "id"]


class ImportBatch(TenantValidatedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    source = models.CharField(max_length=40)
    batch_key = models.CharField(max_length=128)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    row_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="influencer_import_batches")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    tenant_relation_fields = ("created_by",)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "source", "batch_key"], name="uniq_influencer_import_batch")]


class StoreProductListing(TenantValidatedModel):
    store = models.ForeignKey(StoreMaster, on_delete=models.PROTECT, related_name="influencer_product_listings")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, null=True, blank=True, related_name="store_listings")
    external_product_id = models.CharField(max_length=120)
    parent_sku = models.CharField(max_length=120, blank=True)
    product_name = models.CharField(max_length=240)
    site_code = models.CharField(max_length=16)
    source = models.CharField(max_length=40)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("store", "spu")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "store", "site_code", "external_product_id"], name="uniq_store_external_product")]
        indexes = [models.Index(fields=["tenant", "external_product_id"], name="idx_listing_product_id")]


class SkuPriceSnapshot(TenantValidatedModel):
    listing = models.ForeignKey(StoreProductListing, on_delete=models.CASCADE, related_name="sku_prices")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, null=True, blank=True, related_name="store_price_snapshots")
    external_sku = models.CharField(max_length=120)
    variant_id = models.CharField(max_length=120, blank=True)
    variant_name = models.CharField(max_length=160, blank=True)
    original_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    promotion_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    effective_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    inbound_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=8)
    stock = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=40)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    cost_updated_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("listing", "sku")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "listing", "external_sku", "variant_id"], name="uniq_listing_external_sku")]
        indexes = [models.Index(fields=["tenant", "external_sku"], name="idx_snapshot_external_sku")]


class ExternalSourceRecord(TenantValidatedModel):
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="source_records")
    source = models.CharField(max_length=40)
    external_id = models.CharField(max_length=160)
    record_type = models.CharField(max_length=60)
    payload_hash = models.CharField(max_length=64)
    target_model = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("batch",)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "source", "record_type", "external_id"], name="uniq_influencer_source_record")]


class AffiliateOrderSnapshot(TenantValidatedModel):
    """The current, whitelisted SKU-level fact imported from an affiliate report."""

    source = models.CharField(max_length=40)
    source_row_key = models.CharField(max_length=64)
    row_hash = models.CharField(max_length=64)
    data_time = models.DateTimeField()
    shop_name = models.CharField(max_length=160, blank=True)
    shop_abbr = models.CharField(max_length=80)
    site = models.CharField(max_length=32)
    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="influencer_affiliate_orders",
    )
    order_id = models.CharField(max_length=160)
    product_id = models.CharField(max_length=160)
    product_name = models.CharField(max_length=240, blank=True)
    sku_id = models.CharField(max_length=160)
    product_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    payment_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    currency = models.CharField(max_length=3, choices=SUPPORTED_CURRENCY_CHOICES)
    quantity = models.PositiveIntegerField(default=0)
    fully_returned = models.CharField(max_length=20, default="否")
    order_status = models.CharField(max_length=40)
    creator_username = models.CharField(max_length=160)
    creator_username_normalized = models.CharField(max_length=160, blank=True, default="", db_index=True)
    actual_paid_commission = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    estimated_paid_commission = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("store",)

    class Meta:
        ordering = ["tenant_id", "data_time", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source", "source_row_key"],
                name="uniq_affiliate_order_source_row",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "data_time", "creator_username_normalized", "shop_abbr", "product_id"],
                name="idx_aff_order_date_creator",
            ),
            models.Index(
                fields=["tenant", "creator_username_normalized", "shop_abbr", "site", "product_id", "data_time"],
                name="idx_aff_order_creator_shop",
            ),
            models.Index(
                fields=["tenant", "shop_abbr", "site", "order_id", "sku_id"],
                name="idx_aff_order_shop_order_sku",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.creator_username_normalized:
            self.creator_username_normalized = self.creator_username.strip().casefold()
        if self.store_id and self.store.tenant_id != self.tenant_id:
            raise ValidationError({"store": "Store must belong to the same tenant."})


class AffiliateOrderRevision(TenantValidatedModel):
    """Auditable before/after values for a changed affiliate order fact."""

    order_snapshot = models.ForeignKey(
        AffiliateOrderSnapshot,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    source = models.CharField(max_length=40)
    source_row_key = models.CharField(max_length=64)
    revision_no = models.PositiveIntegerField()
    before_hash = models.CharField(max_length=64)
    after_hash = models.CharField(max_length=64)
    before_values = models.JSONField(default=dict)
    after_values = models.JSONField(default=dict)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("order_snapshot",)

    class Meta:
        ordering = ["tenant_id", "source_row_key", "revision_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source", "source_row_key", "revision_no"],
                name="uniq_affiliate_order_revision",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "source_row_key", "revision_no"],
                name="idx_aff_order_revision_key",
            ),
        ]


class AffiliateImportState(TenantValidatedModel):
    """Tenant/source cursor and short-lived lease for a repeatable import job."""

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=40)
    cursor = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IDLE)
    lease_token = models.CharField(max_length=64, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_data_time = models.DateTimeField(null=True, blank=True)
    last_source_updated_at = models.DateTimeField(null=True, blank=True)
    last_row_count = models.PositiveIntegerField(default=0)
    last_rejected_count = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "source"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source"],
                name="uniq_affiliate_import_state",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "lease_expires_at"], name="idx_aff_import_lease"),
        ]


class BdSampleAttributionSnapshot(TenantValidatedModel):
    """Frozen sample facts used for later BD attribution."""

    fulfillment = models.OneToOneField(
        SampleFulfillment,
        on_delete=models.PROTECT,
        related_name="bd_attribution_snapshot",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bd_sample_attribution_snapshots",
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        related_name="bd_sample_attribution_snapshots",
    )
    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.PROTECT,
        related_name="bd_sample_attribution_snapshots",
    )
    creator_username = models.CharField(max_length=255, blank=True)
    shop_abbr = models.CharField(max_length=80)
    site = models.CharField(max_length=32)
    product_id = models.CharField(max_length=160, blank=True)
    product_name = models.CharField(max_length=240, blank=True)
    sku_id = models.CharField(max_length=160, blank=True)
    sampled_at = models.DateTimeField()
    shipped_at = models.DateTimeField(null=True, blank=True)
    sample_status = models.CharField(max_length=20)
    cost_amount = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=3, choices=SUPPORTED_CURRENCY_CHOICES)
    pricing_status = models.CharField(max_length=20)
    source = models.CharField(max_length=40, default="fulfillment")
    legacy_inferred = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("fulfillment", "owner", "influencer", "store")

    class Meta:
        ordering = ["tenant_id", "sampled_at", "id"]
        indexes = [
            models.Index(
                fields=["tenant", "creator_username", "shop_abbr", "product_id", "sampled_at"],
                name="idx_bd_sample_match",
            ),
            models.Index(fields=["tenant", "owner", "sampled_at"], name="idx_bd_sample_owner_date"),
        ]

    @property
    def influencer_account(self):
        return self.creator_username


class BdOrderAttributionSnapshot(TenantValidatedModel):
    """One deterministic owner result for an imported affiliate order line."""

    class Rule(models.TextChoices):
        STRICT = "strict", "Strict"
        FALLBACK = "fallback", "Fallback"

    order_snapshot = models.ForeignKey(
        AffiliateOrderSnapshot,
        on_delete=models.PROTECT,
        related_name="bd_attribution_snapshots",
    )
    sample_attribution = models.ForeignKey(
        BdSampleAttributionSnapshot,
        on_delete=models.PROTECT,
        related_name="order_attribution_snapshots",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bd_order_attribution_snapshots",
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        related_name="bd_order_attribution_snapshots",
    )
    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bd_order_attribution_snapshots",
    )
    order_id = models.CharField(max_length=160)
    sku_id = models.CharField(max_length=160)
    product_id = models.CharField(max_length=160)
    rule = models.CharField(max_length=20, choices=Rule.choices)
    rule_version = models.CharField(max_length=64)
    attributed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("order_snapshot", "sample_attribution", "owner", "influencer", "store")

    class Meta:
        ordering = ["tenant_id", "order_id", "sku_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "order_snapshot", "rule_version"],
                name="uniq_bd_order_attribution_version",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "owner", "attributed_at"], name="idx_bd_order_owner_date"),
            models.Index(fields=["tenant", "rule", "rule_version"], name="idx_bd_order_rule_version"),
        ]


class InfluencerProfile(TenantValidatedModel):
    """Extended, tenant-scoped business profile for an influencer."""

    influencer = models.OneToOneField(
        Influencer,
        on_delete=models.PROTECT,
        related_name="profile",
    )
    display_name = models.CharField(max_length=160, blank=True)
    external_influencer_id = models.CharField(max_length=160, blank=True)
    level = models.CharField(max_length=40, blank=True)
    tier = models.CharField(max_length=40, blank=True)
    average_video_views = models.PositiveBigIntegerField(default=0)
    average_live_views = models.PositiveBigIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    market = models.CharField(max_length=40, blank=True)
    platforms = models.JSONField(default=list, blank=True)
    content_types = models.JSONField(default=list, blank=True)
    profile_url = models.URLField(max_length=500, blank=True)
    duplicate_reason = models.CharField(max_length=240, blank=True)
    product_cooperation_count = models.PositiveIntegerField(default=0)
    first_cooperation_at = models.DateTimeField(null=True, blank=True)
    cooperation_count = models.PositiveIntegerField(default=0)
    completed_cooperation_count = models.PositiveIntegerField(default=0)
    fulfilled_cooperation_count = models.PositiveIntegerField(default=0)
    fulfillment_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    content_completion_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    historical_gmv = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    historical_orders = models.PositiveBigIntegerField(default=0)
    historical_performance = models.JSONField(default=dict, blank=True)
    profile_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer",)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fulfillment_rate__isnull=True)
                | models.Q(fulfillment_rate__gte=0, fulfillment_rate__lte=1),
                name="chk_inf_fulfill_rate",
            ),
            models.CheckConstraint(
                condition=models.Q(content_completion_rate__isnull=True)
                | models.Q(content_completion_rate__gte=0, content_completion_rate__lte=1),
                name="chk_inf_content_rate",
            ),
        ]


class InfluencerContact(TenantValidatedModel):
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        related_name="contacts",
    )
    channel = models.CharField(max_length=40)
    value = models.CharField(max_length=240)
    label = models.CharField(max_length=80, blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="influencer_contacts_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer", "created_by")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "influencer", "channel", "value"],
                name="uniq_inf_contact_value",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "influencer", "is_active"],
                name="idx_inf_contact_active",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_primary and self.influencer_id:
            other_primary = type(self).objects.filter(
                tenant_id=self.tenant_id,
                influencer_id=self.influencer_id,
                is_primary=True,
                is_active=True,
            )
            if self.pk:
                other_primary = other_primary.exclude(pk=self.pk)
            if other_primary.exists():
                raise ValidationError({"is_primary": "Only one active primary contact is allowed."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Influencer.objects.select_for_update().get(
                pk=self.influencer_id,
                tenant_id=self.tenant_id,
            )
            return super().save(*args, **kwargs)


class ImmutableEventQuerySet(TenantValidatedQuerySet):
    def delete(self):
        raise ValidationError("Restriction events are immutable.")


class InfluencerRestrictEvent(TenantValidatedModel):
    class Action(models.TextChoices):
        BLACKLIST = "blacklist", "Blacklist"
        UNBLACKLIST = "unblacklist", "Unblacklist"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="influencer_restrict_events",
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        related_name="restrict_events",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    reason = models.CharField(max_length=240)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="influencer_restrict_events",
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=40, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_relation_fields = ("influencer", "actor")
    objects = ImmutableEventQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "influencer_id", "occurred_at", "id"]
        indexes = [
            models.Index(
                fields=["tenant", "influencer", "occurred_at"],
                name="idx_inf_restrict_time",
            ),
        ]

    def _assert_immutable(self):
        if self.pk is not None and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Influencer restriction events are immutable.")

    def save(self, *args, **kwargs):
        self._assert_immutable()
        return super().save(*args, **kwargs)

    def save_base(self, *args, **kwargs):
        self._assert_immutable()
        return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Influencer restriction events are immutable.")


class VideoResult(TenantValidatedModel):
    class ContentType(models.TextChoices):
        VIDEO = "video", "Video"
        LIVE = "live", "Live"

    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.PROTECT,
        related_name="video_results",
    )
    outreach_task = models.ForeignKey(
        OutreachTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="video_results",
    )
    sample_fulfillment = models.ForeignKey(
        SampleFulfillment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="video_results",
    )
    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="influencer_video_results",
    )
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    platform = models.CharField(max_length=40)
    external_content_id = models.CharField(max_length=160)
    url = models.URLField(max_length=500, blank=True)
    title = models.CharField(max_length=240, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    metric_date = models.DateField()
    views = models.PositiveBigIntegerField(default=0)
    live_views = models.PositiveBigIntegerField(default=0)
    orders = models.PositiveBigIntegerField(default=0)
    gmv = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    currency = models.CharField(max_length=8)
    source = models.CharField(max_length=40, default="manual")
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("influencer", "outreach_task", "sample_fulfillment", "store")

    class Meta:
        ordering = ["tenant_id", "metric_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "external_content_id"],
                name="uniq_vres_platform_ext",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "influencer", "metric_date"],
                name="idx_vres_creator_date",
            ),
            models.Index(
                fields=["tenant", "outreach_task", "metric_date"],
                name="idx_vres_task_date",
            ),
        ]

    def clean(self):
        super().clean()
        if self.outreach_task_id:
            task = OutreachTask.objects.filter(pk=self.outreach_task_id).values(
                "influencer_id", "store_id"
            ).first()
            if (
                task is not None
                and task["influencer_id"] is not None
                and task["influencer_id"] != self.influencer_id
            ):
                raise ValidationError({"outreach_task": "Outreach task must match the influencer."})
            if task is not None and self.store_id and task["store_id"] != self.store_id:
                raise ValidationError({"store": "Store must match the outreach task."})
        if self.sample_fulfillment_id:
            fulfillment = SampleFulfillment.objects.filter(pk=self.sample_fulfillment_id).values(
                "influencer_id", "outreach_task_id", "store_id"
            ).first()
            if fulfillment is not None and fulfillment["influencer_id"] != self.influencer_id:
                raise ValidationError({"sample_fulfillment": "Sample fulfillment must match the influencer."})
            if (
                fulfillment is not None
                and self.outreach_task_id
                and fulfillment["outreach_task_id"] != self.outreach_task_id
            ):
                raise ValidationError({"sample_fulfillment": "Sample fulfillment must match the outreach task."})
            if (
                fulfillment is not None
                and self.outreach_task_id
                and task is not None
                and fulfillment["store_id"] != task["store_id"]
            ):
                raise ValidationError({"sample_fulfillment": "Sample fulfillment must match the outreach task store."})
            if fulfillment is not None and self.store_id and fulfillment["store_id"] != self.store_id:
                raise ValidationError({"store": "Store must match the sample fulfillment."})


class TikTokVideoSyncBatch(TenantValidatedModel):
    """Auditable, tenant-scoped envelope for one TikTok video sync window."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.PROTECT,
        related_name="tiktok_video_sync_batches",
    )
    window_start = models.DateField()
    window_end = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    api_version = models.CharField(max_length=20)
    idempotency_key = models.CharField(max_length=160)
    page_count = models.PositiveIntegerField(default=0)
    video_count = models.PositiveIntegerField(default=0)
    detail_requested_count = models.PositiveIntegerField(default=0)
    detail_succeeded_count = models.PositiveIntegerField(default=0)
    detail_failed_count = models.PositiveIntegerField(default=0)
    request_cursor = models.TextField(blank=True, default="")
    lease_token = models.CharField(max_length=64, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    latest_available_date = models.DateField(null=True, blank=True)
    error_summary = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("store",)

    class Meta:
        ordering = ["tenant_id", "window_start", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store", "idempotency_key"],
                name="uniq_tk_batch_idempotency",
            ),
            models.UniqueConstraint(
                fields=["tenant", "store", "window_start", "window_end", "api_version"],
                name="uniq_tk_batch_window_job",
            ),
            models.CheckConstraint(
                condition=models.Q(window_start__lt=models.F("window_end")),
                name="chk_tk_batch_window",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1, attempt_count__lte=models.F("max_attempts")),
                name="chk_tk_batch_attempts",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="running")
                    | models.Q(
                        lease_token__gt="",
                        lease_expires_at__isnull=False,
                        heartbeat_at__isnull=False,
                        lease_expires_at__gt=models.F("heartbeat_at"),
                    )
                ),
                name="chk_tk_batch_running_lease",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "store", "status", "window_start"],
                name="idx_tk_batch_store_state",
            ),
            models.Index(
                fields=["tenant", "store", "window_start", "window_end"],
                name="idx_tk_batch_store_window",
            ),
        ]

    def clean(self):
        super().clean()
        if self.window_start and self.window_end and self.window_start >= self.window_end:
            raise ValidationError({"window_end": "The sync window end must be after its start."})
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            raise ValidationError({"completed_at": "Completion cannot precede the start time."})
        if self.detail_succeeded_count + self.detail_failed_count > self.detail_requested_count:
            raise ValidationError({"detail_requested_count": "Detail results cannot exceed requested details."})
        if self.max_attempts < 1 or self.attempt_count > self.max_attempts:
            raise ValidationError({"attempt_count": "Attempt count must not exceed a positive maximum."})
        if self.status == self.Status.RUNNING:
            required = {
                "lease_token": self.lease_token,
                "lease_expires_at": self.lease_expires_at,
                "heartbeat_at": self.heartbeat_at,
            }
            missing = [field for field, value in required.items() if not value]
            if missing:
                raise ValidationError({field: "Running sync requires this lease field." for field in missing})
            if self.lease_expires_at and self.heartbeat_at and self.lease_expires_at <= self.heartbeat_at:
                raise ValidationError({"lease_expires_at": "Running sync lease must expire after its heartbeat."})


class TikTokShopVideo(TenantValidatedModel):
    """The stable identity and descriptive snapshot of a TikTok Shop video."""

    class VideoType(models.TextChoices):
        SELF_OPERATED = "self_operated", "Self operated"
        CREATOR = "creator", "Creator"

    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.PROTECT,
        related_name="tiktok_shop_videos",
    )
    influencer = models.ForeignKey(
        Influencer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tiktok_shop_videos",
    )
    external_video_id = models.CharField(max_length=160)
    creator_id = models.CharField(max_length=160, blank=True, default="")
    creator_open_id = models.CharField(max_length=160, blank=True, default="")
    creator_username = models.CharField(max_length=160, blank=True, default="")
    creator_username_normalized = models.CharField(max_length=160, blank=True, default="")
    title = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    video_type = models.CharField(max_length=30, choices=VideoType.choices, default=VideoType.CREATOR)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    source_api = models.CharField(max_length=80, default="tiktok_shop")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("store", "influencer")

    class Meta:
        ordering = ["tenant_id", "-last_seen_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store", "external_video_id"],
                name="uniq_tk_video_external_id",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "last_seen_at"], name="idx_tk_video_store_seen"),
            models.Index(
                fields=["tenant", "creator_username_normalized"],
                name="idx_tk_video_creator",
            ),
        ]

    def clean(self):
        super().clean()
        normalized = self.creator_username.strip().lstrip("@").casefold()
        self.creator_username_normalized = normalized
        if self.first_seen_at and self.last_seen_at and self.first_seen_at > self.last_seen_at:
            raise ValidationError({"last_seen_at": "Last seen time cannot precede first seen time."})


class TikTokVideoProduct(TenantValidatedModel):
    """A product parsed or returned for a TikTok Shop video."""

    class ParseStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PARSED = "parsed", "Parsed"
        UNMATCHED = "unmatched", "Unmatched"
        FAILED = "failed", "Failed"

    video = models.ForeignKey(
        TikTokShopVideo,
        on_delete=models.PROTECT,
        related_name="video_products",
    )
    external_product_id = models.CharField(max_length=160)
    name = models.CharField(max_length=240, blank=True, default="")
    source = models.CharField(max_length=40, default="api")
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    parse_status = models.CharField(max_length=20, choices=ParseStatus.choices, default=ParseStatus.PENDING)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("video",)

    class Meta:
        ordering = ["tenant_id", "video_id", "external_product_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "video", "external_product_id"],
                name="uniq_tk_vprod_external",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0, confidence__lte=1),
                name="chk_tk_vprod_confidence",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "video", "parse_status"], name="idx_tk_vprod_parse"),
            models.Index(fields=["tenant", "external_product_id"], name="idx_tk_vprod_ext_id"),
        ]

    def clean(self):
        super().clean()
        if self.first_seen_at and self.last_seen_at and self.first_seen_at > self.last_seen_at:
            raise ValidationError({"last_seen_at": "Last seen time cannot precede first seen time."})


class TikTokVideoDailyMetric(TenantValidatedModel):
    """One original-currency daily performance fact for a TikTok video."""

    class QualityStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        DEGRADED = "degraded", "Degraded"
        FAILED = "failed", "Failed"
        MISSING = "missing", "Missing"
        UNKNOWN = "unknown", "Unknown"

    video = models.ForeignKey(
        TikTokShopVideo,
        on_delete=models.PROTECT,
        related_name="daily_metrics",
    )
    store = models.ForeignKey(
        StoreMaster,
        on_delete=models.PROTECT,
        related_name="tiktok_video_daily_metrics",
    )
    batch = models.ForeignKey(
        TikTokVideoSyncBatch,
        on_delete=models.PROTECT,
        related_name="daily_metrics",
    )
    metric_date = models.DateField()
    currency = models.CharField(max_length=8)
    currency_basis = models.CharField(max_length=40, default="api_original")
    views = models.PositiveBigIntegerField(default=0)
    likes = models.PositiveBigIntegerField(default=0)
    comments = models.PositiveBigIntegerField(default=0)
    shares = models.PositiveBigIntegerField(default=0)
    new_followers = models.PositiveBigIntegerField(default=0)
    v_to_l_clicks = models.PositiveBigIntegerField(default=0)
    product_impressions = models.PositiveBigIntegerField(default=0)
    product_clicks = models.PositiveBigIntegerField(default=0)
    unique_customers = models.PositiveBigIntegerField(default=0)
    orders = models.PositiveBigIntegerField(default=0)
    items_sold = models.PositiveBigIntegerField(default=0)
    attributed_gmv = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    direct_gmv = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    indirect_gmv = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    gpm = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    ctr = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    v_to_l_rate = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    finish_rate = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    click_to_order_rate = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    quality_status = models.CharField(
        max_length=20,
        choices=QualityStatus.choices,
        default=QualityStatus.UNKNOWN,
    )
    diagnosis = models.TextField(blank=True, default="")
    row_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("video", "store", "batch")

    class Meta:
        ordering = ["tenant_id", "metric_date", "video_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "video", "metric_date"],
                name="uniq_tk_vmetric_day",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(attributed_gmv__gte=0)
                    & models.Q(direct_gmv__gte=0)
                    & models.Q(indirect_gmv__gte=0)
                    & models.Q(gpm__gte=0)
                ),
                name="chk_tk_vmetric_amounts",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(ctr__gte=0, ctr__lte=1)
                    & models.Q(v_to_l_rate__gte=0, v_to_l_rate__lte=1)
                    & models.Q(finish_rate__gte=0, finish_rate__lte=1)
                    & models.Q(click_to_order_rate__gte=0, click_to_order_rate__lte=1)
                ),
                name="chk_tk_vmetric_rates",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "store", "metric_date"],
                name="idx_tk_vmetric_store",
            ),
            models.Index(fields=["tenant", "batch"], name="idx_tk_vmetric_batch"),
            models.Index(
                fields=["tenant", "quality_status", "metric_date"],
                name="idx_tk_vmetric_quality",
            ),
        ]

    def clean(self):
        super().clean()
        if self.currency:
            self.currency = self.currency.strip().upper()
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError({"currency": "Currency must be a three-letter ISO code."})
        if self.video_id and self.store_id and self.video.store_id != self.store_id:
            raise ValidationError({"store": "Metric store must match the video store."})
        if self.batch_id and self.store_id and self.batch.store_id != self.store_id:
            raise ValidationError({"batch": "Metric batch must match the metric store."})
        store_currency = (self.store.currency or "").strip().upper() if self.store_id else ""
        if store_currency and self.currency != store_currency:
            raise ValidationError({"currency": "API-original currency must match the store currency."})


class ImmutableAttributionQuerySet(TenantValidatedQuerySet):
    def update(self, **kwargs):
        raise ValidationError("BD video attribution evidence is immutable.")

    def delete(self):
        raise ValidationError("BD video attribution evidence is immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("BD video attribution evidence is immutable.")


class BDVideoAttribution(TenantValidatedModel):
    """Immutable, versioned evidence for one BD video-attribution calculation."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        MATCHED = "matched", "Matched"
        UNMATCHED = "unmatched", "Unmatched"
        INELIGIBLE = "ineligible", "Ineligible"
        FAILED = "failed", "Failed"

    video = models.ForeignKey(
        TikTokShopVideo,
        on_delete=models.PROTECT,
        related_name="bd_video_attributions",
    )
    matched_product = models.ForeignKey(
        TikTokVideoProduct,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bd_video_attributions",
    )
    sample_fulfillment = models.ForeignKey(
        SampleFulfillment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bd_video_attributions",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bd_video_attributions",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    eligible_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    rule_version = models.CharField(max_length=64)
    input_fingerprint = models.CharField(max_length=64)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("video", "matched_product", "sample_fulfillment", "owner")
    objects = ImmutableAttributionQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "video_id", "rule_version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "video", "rule_version", "input_fingerprint"],
                name="uniq_tk_bd_attr_evidence",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "video", "status"], name="idx_tk_bd_video_state"),
            models.Index(fields=["tenant", "owner", "eligible_at"], name="idx_tk_bd_owner_date"),
            models.Index(fields=["tenant", "rule_version", "created_at"], name="idx_tk_bd_rule_created"),
        ]

    def clean(self):
        super().clean()
        if self.published_at and self.eligible_at and self.published_at < self.eligible_at:
            raise ValidationError({"eligible_at": "Eligibility cannot be after publication."})
        if self.matched_product_id and self.video_id:
            product_video_id = TikTokVideoProduct.objects.filter(
                pk=self.matched_product_id,
                tenant_id=self.tenant_id,
            ).values_list("video_id", flat=True).first()
            if product_video_id is not None and product_video_id != self.video_id:
                raise ValidationError({"matched_product": "Matched product must belong to the video."})
        if self.status == self.Status.MATCHED:
            required = {
                "matched_product": self.matched_product_id,
                "sample_fulfillment": self.sample_fulfillment_id,
                "owner": self.owner_id,
                "published_at": self.published_at,
                "eligible_at": self.eligible_at,
            }
            missing = [field for field, value in required.items() if not value]
            if missing:
                raise ValidationError({field: "Matched attribution requires this field." for field in missing})

    def save(self, *args, **kwargs):
        if self.pk or not self._state.adding:
            raise ValidationError("BD video attribution evidence is immutable; create a new version instead.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("BD video attribution evidence is immutable.")


class BDVideoAttributionCurrent(TenantValidatedModel):
    """MySQL-safe pointer to the current attribution evidence for a video and rule."""

    video = models.ForeignKey(
        TikTokShopVideo,
        on_delete=models.PROTECT,
        related_name="current_bd_attributions",
    )
    attribution = models.ForeignKey(
        BDVideoAttribution,
        on_delete=models.PROTECT,
        related_name="current_pointers",
    )
    rule_version = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("video", "attribution")

    class Meta:
        ordering = ["tenant_id", "video_id", "rule_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "video", "rule_version"],
                name="uniq_tk_bd_current_pointer",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "rule_version"], name="idx_tk_bd_current_rule"),
        ]

    def clean(self):
        super().clean()
        if not self.attribution_id:
            return
        evidence = BDVideoAttribution.objects.filter(
            pk=self.attribution_id,
            tenant_id=self.tenant_id,
        ).values("video_id", "rule_version").first()
        if evidence is None:
            return
        if self.video_id and evidence["video_id"] != self.video_id:
            raise ValidationError({"attribution": "Current evidence must belong to the selected video."})
        if self.rule_version and evidence["rule_version"] != self.rule_version:
            raise ValidationError({"rule_version": "Current pointer and evidence must use the same rule version."})


class ExchangeRate(TenantValidatedModel):
    base_currency = models.CharField(max_length=8)
    quote_currency = models.CharField(max_length=8)
    rate = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        validators=[MinValueValidator(Decimal("0.0000000001"))],
    )
    effective_from = models.DateField()
    source = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exchange_rates_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_relation_fields = ("created_by",)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "base_currency", "quote_currency", "effective_from", "source"],
                name="uniq_fx_pair_start_src",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gt=0),
                name="chk_fx_rate_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "tenant",
                    "base_currency",
                    "quote_currency",
                    "effective_from",
                    "is_active",
                ],
                name="idx_fx_pair_effective",
            ),
        ]
