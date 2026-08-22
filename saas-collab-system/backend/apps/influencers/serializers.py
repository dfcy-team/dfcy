from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.masterdata.models import StoreMaster

from .models import (
    Influencer,
    InfluencerContact,
    InfluencerProfile,
    InfluencerRestrictEvent,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
    VideoResult,
)


def _mask_text(value, *, suffix_length=2):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= suffix_length + 1:
        return "*" * len(text)
    return f"{text[:1]}***{text[-suffix_length:]}"


def mask_handle(value):
    text = str(value or "").strip()
    if not text:
        return ""
    prefix = "@" if text.startswith("@") else ""
    return prefix + _mask_text(text[len(prefix):])


def mask_contact_value(value, channel=""):
    text = str(value or "").strip()
    if not text:
        return ""
    if channel == "email" and "@" in text:
        local, domain = text.split("@", 1)
        return f"{local[:1]}***@{domain}"
    if channel == "phone":
        return f"***{text[-4:]}"
    return _mask_text(text)


def mask_profile_value(value):
    return _mask_text(value, suffix_length=4)


def safe_influencer_name(value):
    name = str(getattr(value, "name", "") or "").strip()
    handle = str(getattr(value, "handle", "") or "").strip()
    if name and handle and name.casefold() == handle.casefold():
        return mask_handle(name)
    return name


class InfluencerProfileSerializer(serializers.ModelSerializer):
    external_influencer_id = serializers.CharField(write_only=True, required=False, allow_blank=True)
    external_influencer_id_masked = serializers.SerializerMethodField()
    profile_url = serializers.URLField(write_only=True, required=False, allow_blank=True)
    profile_url_masked = serializers.SerializerMethodField()
    profile_notes = serializers.CharField(write_only=True, required=False, allow_blank=True)
    profile_notes_masked = serializers.SerializerMethodField()

    class Meta:
        model = InfluencerProfile
        fields = (
            "id", "display_name", "external_influencer_id", "external_influencer_id_masked",
            "level", "tier", "average_video_views", "average_live_views", "is_active", "market",
            "platforms", "content_types", "profile_url", "profile_url_masked", "duplicate_reason",
            "product_cooperation_count", "first_cooperation_at", "cooperation_count",
            "completed_cooperation_count", "fulfilled_cooperation_count", "fulfillment_rate",
            "content_completion_rate", "historical_gmv", "historical_orders", "historical_performance",
            "profile_notes", "profile_notes_masked", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "external_influencer_id_masked", "profile_url_masked", "profile_notes_masked",
            "created_at", "updated_at",
        )

    def get_external_influencer_id_masked(self, obj):
        return mask_profile_value(obj.external_influencer_id)

    def get_profile_url_masked(self, obj):
        return mask_profile_value(obj.profile_url)

    def get_profile_notes_masked(self, obj):
        return "***" if obj.profile_notes else ""


class InfluencerContactSerializer(serializers.ModelSerializer):
    value = serializers.CharField(write_only=True, required=False, allow_blank=False)
    masked_value = serializers.SerializerMethodField()

    class Meta:
        model = InfluencerContact
        fields = (
            "id", "channel", "value", "masked_value", "label", "is_primary", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "masked_value", "created_at", "updated_at")

    def get_masked_value(self, obj):
        return mask_contact_value(obj.value, obj.channel)


class InfluencerRestrictEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = InfluencerRestrictEvent
        fields = ("id", "action", "reason", "actor_id", "actor_name", "occurred_at", "source")

    def get_actor_name(self, obj):
        return obj.actor.full_name or obj.actor.username


class InfluencerSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    handle = serializers.CharField(write_only=True, required=False, allow_blank=True)
    handle_masked = serializers.SerializerMethodField()
    contact_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    contact_name_masked = serializers.SerializerMethodField()
    contact_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    contact_phone_masked = serializers.SerializerMethodField()
    contact_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    contact_email_masked = serializers.SerializerMethodField()
    notes = serializers.CharField(write_only=True, required=False, allow_blank=True)
    is_blacklisted = serializers.SerializerMethodField()
    video_metrics = serializers.SerializerMethodField()
    profile = InfluencerProfileSerializer(required=False)
    contacts = InfluencerContactSerializer(many=True, read_only=True)
    blacklist_history = InfluencerRestrictEventSerializer(source="restrict_events", many=True, read_only=True)

    class Meta:
        model = Influencer
        fields = (
            "id", "tenant_id", "code", "name", "platform", "handle", "handle_masked", "category",
            "contact_name", "contact_name_masked", "contact_phone", "contact_phone_masked",
            "contact_email", "contact_email_masked", "notes",
            "follower_count", "cooperation_status", "status", "is_blacklisted", "video_metrics",
            "profile", "contacts", "blacklist_history",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "status", "created_at", "updated_at", "is_blacklisted",
            "handle_masked", "contact_name_masked", "contact_phone_masked", "contact_email_masked",
        )

    def get_handle_masked(self, obj):
        return mask_handle(obj.handle)

    def get_contact_name_masked(self, obj):
        return _mask_text(obj.contact_name)

    def get_contact_phone_masked(self, obj):
        return f"***{obj.contact_phone[-4:]}" if obj.contact_phone else ""

    def get_contact_email_masked(self, obj):
        value = obj.contact_email
        if not value or "@" not in value:
            return ""
        local, domain = value.split("@", 1)
        return f"{local[:1]}***@{domain}"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["name"] = safe_influencer_name(instance)
        return data


    def validate_code(self, value):
        request = self.context["request"]
        queryset = Influencer.objects.filter(tenant=request.user.tenant, code=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Code must be unique within the current tenant.")
        return value

    def get_is_blacklisted(self, obj):
        prefetched = getattr(obj, "_restriction_events", None)
        if prefetched:
            return prefetched[0].action == InfluencerRestrictEvent.Action.BLACKLIST
        restrictions = getattr(obj, "_restriction_rows", None)
        if restrictions is not None:
            return bool(restrictions and restrictions[0].is_blacklisted)
        latest = obj.restrict_events.order_by("-occurred_at", "-id").values_list("action", flat=True).first()
        if latest is not None:
            return latest == "blacklist"
        return obj.restrictions.filter(is_blacklisted=True).exists()

    def get_video_metrics(self, obj):
        # Raw video results can contain millions of rows. Online list/detail
        # requests must use the future daily aggregate rather than scan them.
        return {"status": "pending_precompute", "views": None, "live_views": None, "orders": None, "gmv": None}

    def create(self, validated_data):
        profile_data = validated_data.pop("profile", None)
        instance = super().create(validated_data)
        if profile_data is not None:
            InfluencerProfile.objects.create(tenant=instance.tenant, influencer=instance, **profile_data)
        return instance

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)
        instance = super().update(instance, validated_data)
        if profile_data is not None:
            profile, _ = InfluencerProfile.objects.get_or_create(tenant=instance.tenant, influencer=instance)
            for field, value in profile_data.items():
                setattr(profile, field, value)
            profile.full_clean()
            profile.save()
        return instance


class InfluencerListSerializer(InfluencerSerializer):
    """Collection response without account, contact, note, or history details."""

    class Meta(InfluencerSerializer.Meta):
        fields = tuple(
            field for field in InfluencerSerializer.Meta.fields
            if field not in {
                "handle", "profile", "contacts", "blacklist_history", "contact_name_masked",
                "contact_phone_masked", "contact_email_masked",
            }
        )


class InfluencerSafeDetailSerializer(InfluencerListSerializer):
    """Read-only detail safe for users without influencer management access."""


class OutreachTaskSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    dispatcher_id = serializers.IntegerField(read_only=True)
    linked_count = serializers.SerializerMethodField()
    sample_status_summary = serializers.SerializerMethodField()
    sample_fulfillment_status_summary = serializers.SerializerMethodField()
    sample_fulfillment_count = serializers.SerializerMethodField()
    sample_fulfillment_completed_count = serializers.SerializerMethodField()
    sample_fulfillment_video_match_count = serializers.SerializerMethodField()
    video_match_count = serializers.SerializerMethodField()
    completion_validation = serializers.SerializerMethodField()
    store_name = serializers.CharField(source="store.name", read_only=True)
    owner_name = serializers.SerializerMethodField()
    dispatcher_name = serializers.SerializerMethodField()

    @staticmethod
    def _user_name(user):
        return (getattr(user, "full_name", "") or getattr(user, "username", "")) if user else ""

    def get_owner_name(self, obj):
        return self._user_name(obj.owner)

    def get_dispatcher_name(self, obj):
        return self._user_name(obj.dispatcher)

    def get_linked_count(self, obj):
        annotated = getattr(obj, "active_linked_count", None)
        return annotated if annotated is not None else obj.linked_count

    def _sample_summary(self, obj):
        cached = getattr(obj, "_sample_status_summary", None)
        if cached is not None:
            return cached
        counts = {status: 0 for status, _ in SampleFulfillment.Status.choices}
        prefetched_samples = getattr(obj, "_active_samples", None)
        if prefetched_samples is None:
            sample_rows = list(
                obj.sample_fulfillments.filter(
                    tenant_id=obj.tenant_id,
                    is_deleted=False,
                ).values_list("id", "status")
            )
            sample_ids = [sample_id for sample_id, _ in sample_rows]
            published_video_rows = VideoResult.objects.filter(
                tenant_id=obj.tenant_id,
                sample_fulfillment_id__in=sample_ids,
                published_at__isnull=False,
            )
            matched_videos = published_video_rows.count()
            matched_sample_ids = set(
                published_video_rows.values_list("sample_fulfillment_id", flat=True)
            )
        else:
            sample_rows = [(sample.id, sample.status) for sample in prefetched_samples]
            sample_ids = [sample_id for sample_id, _ in sample_rows]
            matched_videos = sum(
                len(getattr(sample, "_published_video_results", []))
                for sample in prefetched_samples
            )
            matched_sample_ids = {
                sample.id
                for sample in prefetched_samples
                if getattr(sample, "_published_video_results", [])
            }
        protected_statuses = {
            SampleFulfillment.Status.PUBLISHED,
            SampleFulfillment.Status.LIVE_CREATOR,
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        }
        for sample_id, status in sample_rows:
            if sample_id in matched_sample_ids and status not in protected_statuses:
                status = SampleFulfillment.Status.PUBLISHED
            counts[status] = counts.get(status, 0) + 1
        completed = sum(
            counts.get(status, 0)
            for status in (
                SampleFulfillment.Status.PUBLISHED,
                SampleFulfillment.Status.COMPLETED,
                SampleFulfillment.Status.LIVE_CREATOR,
            )
        )
        summary = {
            "counts": counts,
            "status_counts": counts,
            "total": len(sample_ids),
            "completed": completed,
            "video_match_count": matched_videos,
        }
        setattr(obj, "_sample_status_summary", summary)
        return summary

    def get_sample_status_summary(self, obj):
        return self._sample_summary(obj)

    def get_sample_fulfillment_status_summary(self, obj):
        return self._sample_summary(obj)["status_counts"]

    def get_sample_fulfillment_count(self, obj):
        return self._sample_summary(obj)["total"]

    def get_sample_fulfillment_completed_count(self, obj):
        return self._sample_summary(obj)["completed"]

    def get_sample_fulfillment_video_match_count(self, obj):
        return self._sample_summary(obj)["video_match_count"]

    def get_video_match_count(self, obj):
        return self._sample_summary(obj)["video_match_count"]

    def get_completion_validation(self, obj):
        summary = self._sample_summary(obj)
        target_count = obj.target_count
        target_reached = target_count > 0 and summary["completed"] >= target_count
        return {
            "target_count": target_count,
            "completed_count": summary["completed"],
            "target_positive": target_count > 0,
            "target_reached": target_reached,
            "task_completed": obj.status == OutreachTask.Status.COMPLETED,
            "status_consistent": (
                not target_reached
                or obj.status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}
            ),
        }

    class Meta:
        model = OutreachTask
        fields = (
            "id", "tenant_id", "task_no", "task_name", "influencer", "store", "store_name", "spu",
            "external_product_id", "sku_prefix", "product_name_snapshot", "product_match_status",
            "product_match_source", "product_matched_at", "priority", "target_count", "linked_count", "dispatcher_id",
            "owner", "owner_name", "dispatcher_name", "dispatch_time", "outreach_at", "status", "started_at", "finalized_at",
            "is_deleted", "deleted_at", "source", "external_id", "version", "notes",
            "sample_status_summary", "sample_fulfillment_status_summary", "sample_fulfillment_count",
            "sample_fulfillment_completed_count", "sample_fulfillment_video_match_count", "video_match_count",
            "completion_validation", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "task_no", "dispatcher_id", "linked_count", "status", "dispatch_time", "outreach_at",
            "started_at", "finalized_at", "product_matched_at", "is_deleted", "deleted_at", "version",
            "created_at", "updated_at",
        )

        extra_kwargs = {
            "influencer": {"required": False, "allow_null": True},
            "task_name": {"required": False, "allow_blank": True},
            "external_product_id": {"required": False, "allow_blank": True},
            "sku_prefix": {"required": False, "allow_blank": True},
            "target_count": {"required": False, "min_value": 0},
            "notes": {"required": False, "allow_blank": True},
        }

    def validate_external_id(self, value):
        return value or None

    def validate_priority(self, value):
        allowed = {"low", "normal", "high", "urgent"}
        if value not in allowed:
            raise serializers.ValidationError("Priority must be low, normal, high, or urgent.")
        return value


class OutreachTaskUpdateSerializer(serializers.ModelSerializer):
    """Allow-list for task detail edits; workflow state is service-owned."""

    class Meta:
        model = OutreachTask
        fields = (
            "task_name",
            "priority",
            "store",
            "external_product_id",
            "sku_prefix",
            "target_count",
            "owner",
        )
        extra_kwargs = {
            "task_name": {"required": False, "allow_blank": True},
            "external_product_id": {"required": False, "allow_blank": True},
            "sku_prefix": {"required": False, "allow_blank": True},
            "target_count": {"required": False, "min_value": 0},
        }

    def validate_priority(self, value):
        allowed = {"low", "normal", "high", "urgent"}
        if value not in allowed:
            raise serializers.ValidationError("Priority must be low, normal, high, or urgent.")
        return value


class OutreachTargetSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    influencer_code = serializers.CharField(source="influencer.code", read_only=True)
    influencer_name = serializers.CharField(source="influencer.name", read_only=True)
    influencer_platform = serializers.CharField(source="influencer.platform", read_only=True)

    class Meta:
        model = OutreachTarget
        fields = (
            "id", "tenant_id", "task", "influencer", "influencer_code", "influencer_name",
            "influencer_platform", "first_linked_at", "outreach_result",
            "version", "notes", "is_deleted", "deleted_at", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "task", "first_linked_at", "version", "is_deleted", "deleted_at",
            "created_at", "updated_at",
        )

        extra_kwargs = {
            "influencer": {"required": True},
            "notes": {"required": False, "allow_blank": True},
            "outreach_result": {"required": False},
        }


class SampleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SampleItem
        fields = (
            "id", "sku", "external_product_id", "site_code", "requested_sku", "normalized_sku",
            "matched_sku_code", "matched_legacy_sku_code", "product_name", "quantity", "unit_price", "unit_cost",
            "sales_amount", "cost_amount", "currency", "price_match_status", "cost_match_status", "price_source",
            "cost_source", "price_snapshot_at", "cost_snapshot_at", "match_notes", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "normalized_sku", "matched_sku_code", "matched_legacy_sku_code", "unit_price", "unit_cost",
            "sales_amount", "cost_amount", "currency", "price_match_status", "cost_match_status", "price_source",
            "cost_source", "price_snapshot_at", "cost_snapshot_at", "match_notes", "created_at", "updated_at",
        )

    def validate_requested_sku(self, value):
        return value.strip() or None if value is not None else None


class SampleFulfillmentSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    outreach_task = serializers.PrimaryKeyRelatedField(
        queryset=OutreachTask.objects.all(), required=False, allow_null=True
    )
    outreach_target = serializers.PrimaryKeyRelatedField(
        queryset=OutreachTarget.objects.all(), required=False, allow_null=True
    )
    influencer = serializers.PrimaryKeyRelatedField(
        queryset=Influencer.objects.all(), required=False, allow_null=True
    )
    store = serializers.PrimaryKeyRelatedField(
        queryset=StoreMaster.objects.all(),
        required=False,
        allow_null=True,
    )
    owner = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        required=False,
        allow_null=True,
    )
    items = SampleItemSerializer(many=True, required=False)
    outreach_task_no = serializers.CharField(source="outreach_task.task_no", read_only=True)
    outreach_task_name = serializers.CharField(source="outreach_task.task_name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    influencer_name = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    deleted_by_name = serializers.SerializerMethodField()
    video_match_count = serializers.SerializerMethodField()
    video_matches = serializers.SerializerMethodField()

    @staticmethod
    def _display_name(value):
        if not value:
            return ""
        if hasattr(value, "handle"):
            return safe_influencer_name(value) or mask_handle(value.handle)
        return (
            getattr(value, "name", "")
            or getattr(value, "full_name", "")
            or getattr(value, "username", "")
        )

    def get_influencer_name(self, obj):
        return self._display_name(obj.influencer)

    def get_owner_name(self, obj):
        return self._display_name(obj.owner)

    def get_deleted_by_name(self, obj):
        return self._display_name(obj.deleted_by)

    @staticmethod
    def _published_videos(obj):
        cached = getattr(obj, "_published_video_results", None)
        if cached is not None:
            return cached
        cached = list(
            obj.video_results.filter(
                tenant_id=obj.tenant_id,
                published_at__isnull=False,
            ).order_by(
                "-published_at", "-id"
            )[:50]
        )
        setattr(obj, "_published_video_results", cached)
        return cached

    def get_video_match_count(self, obj):
        return len(self._published_videos(obj))

    def get_video_matches(self, obj):
        return [
            {
                "id": video.id,
                "content_type": video.content_type,
                "platform": video.platform,
                "external_content_id": video.external_content_id,
                "url": video.url,
                "title": video.title,
                "published_at": video.published_at,
                "metric_date": video.metric_date,
            }
            for video in self._published_videos(obj)
        ]

    def validate(self, attrs):
        # Legacy target payloads may derive influencer from the target; targetless creates cannot.
        if attrs.get("outreach_target") is None and attrs.get("influencer") is None:
            raise serializers.ValidationError(
                {"influencer": "This field is required when outreach_target is omitted."}
            )
        return attrs

    class Meta:
        model = SampleFulfillment
        fields = (
            "id", "tenant_id", "fulfillment_no", "outreach_task", "outreach_task_no", "outreach_task_name",
            "outreach_target", "influencer", "influencer_name", "store", "store_name", "owner", "owner_name",
            "product_name_snapshot", "external_product_id", "sample_order_no",
            "link_type", "quick_tags", "sample_sent_at", "shipped_at", "video_deadline_at", "status", "source", "external_id", "version",
            "notes", "finalized_at", "sku_quantity", "sales_amount", "calculated_cost", "pricing_status",
            "priced_at", "is_deleted", "deleted_at", "deleted_by", "deleted_by_name", "video_match_count", "video_matches",
            "items", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "sample_sent_at", "shipped_at", "status",
            "version", "finalized_at", "sku_quantity", "sales_amount", "calculated_cost", "pricing_status",
            "priced_at", "video_deadline_at", "is_deleted", "deleted_at", "deleted_by", "deleted_by_name",
            "video_match_count", "video_matches", "created_at", "updated_at",
        )

        extra_kwargs = {
            "fulfillment_no": {"required": False, "allow_blank": True},
            "external_product_id": {"required": False, "allow_blank": True},
            "sample_order_no": {"required": False, "allow_blank": True},
            "source": {"required": False},
            "external_id": {"required": False, "allow_null": True, "allow_blank": True},
            "notes": {"required": False, "allow_blank": True},
        }

    def validate_external_id(self, value):
        return value or None

    def validate_quick_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Quick tags must be a list.")
        normalized = []
        for raw_tag in value:
            tag = str(raw_tag or "").strip()
            if not tag:
                raise serializers.ValidationError("Quick tags cannot be empty.")
            if len(tag) > 80:
                raise serializers.ValidationError("Each quick tag must be at most 80 characters.")
            if tag not in normalized:
                normalized.append(tag)
        if len(normalized) > 20:
            raise serializers.ValidationError("At most 20 quick tags are allowed.")
        return normalized


class SampleFulfillmentUpdateSerializer(serializers.ModelSerializer):
    """Allow-list for fact edits; status and lifecycle metadata remain service-owned."""

    items = SampleItemSerializer(many=True, required=False)
    append_items = SampleItemSerializer(many=True, required=False, write_only=True)
    items_mode = serializers.ChoiceField(
        choices=("replace", "append"), required=False, write_only=True
    )

    class Meta:
        model = SampleFulfillment
        fields = (
            "sample_order_no",
            "notes",
            "link_type",
            "quick_tags",
            "items",
            "append_items",
            "items_mode",
        )
        extra_kwargs = {
            "sample_order_no": {"required": False, "allow_blank": True},
            "notes": {"required": False, "allow_blank": True},
            "quick_tags": {"required": False},
        }

    def validate_quick_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Quick tags must be a list.")
        normalized = []
        for raw_tag in value:
            tag = str(raw_tag or "").strip()
            if not tag:
                raise serializers.ValidationError("Quick tags cannot be empty.")
            if len(tag) > 80:
                raise serializers.ValidationError("Each quick tag must be at most 80 characters.")
            if tag not in normalized:
                normalized.append(tag)
        if len(normalized) > 20:
            raise serializers.ValidationError("At most 20 quick tags are allowed.")
        return normalized

    def validate(self, attrs):
        if "items" in attrs and "append_items" in attrs:
            raise serializers.ValidationError(
                {"items": "Use either items replacement or append_items, not both."}
            )
        return attrs


class SkuPriceSnapshotSerializer(serializers.ModelSerializer):
    store_id = serializers.IntegerField(source="listing.store_id", read_only=True)
    store_name = serializers.CharField(source="listing.store.name", read_only=True)
    site_code = serializers.CharField(source="listing.site_code", read_only=True)
    product_id = serializers.CharField(source="listing.external_product_id", read_only=True)
    product_name = serializers.CharField(source="listing.product_name", read_only=True)
    parent_sku = serializers.CharField(source="listing.parent_sku", read_only=True)

    class Meta:
        model = SkuPriceSnapshot
        fields = (
            "id", "store_id", "store_name", "site_code", "product_id", "product_name",
            "parent_sku", "external_sku", "variant_id", "variant_name", "original_price",
            "promotion_price", "effective_price", "currency", "source_updated_at", "imported_at",
        )
