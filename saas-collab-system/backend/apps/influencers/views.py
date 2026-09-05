import csv
import hashlib
from io import StringIO
from datetime import timedelta

from django.db import IntegrityError, models, transaction
from django.db.models import BooleanField, Case, Exists, Max, OuterRef, Prefetch, Q, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.accounts.models import CustomUser
from apps.common.responses import paginated_data, success_response
from apps.development.permissions import any_permission_class
from apps.masterdata.models import StatusChoices, StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.tenants.models import Tenant

from .attribution import (
    build_bd_performance,
    default_performance_dates,
    parse_performance_date,
)
from .models import (
    AffiliateOrderSnapshot,
    Influencer,
    InfluencerContact,
    InfluencerRestrictEvent,
    InfluencerRestriction,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SkuPriceSnapshot,
    StoreProductListing,
    VideoResult,
    active_influencer_restriction_subquery,
    influencer_has_active_restriction,
    is_valid_tiktok_username,
    lock_influencer_identity_change,
    normalize_tiktok_username,
)
from .serializers import (
    InfluencerSerializer,
    InfluencerPublicSerializer,
    InfluencerContactSerializer,
    InfluencerRestrictEventSerializer,
    OutreachTargetSerializer,
    OutreachTaskSerializer,
    OutreachTaskUpdateSerializer,
    SampleFulfillmentSerializer,
    SampleFulfillmentUpdateSerializer,
    SkuPriceSnapshotSerializer,
)
from .services import (
    create_outreach_task,
    create_sample_fulfillment,
    add_outreach_target,
    outreach_task_progress,
    restore_outreach_task,
    restore_sample_fulfillment,
    soft_delete_outreach_target,
    soft_delete_outreach_task,
    soft_delete_sample_fulfillment,
    transition_outreach_task,
    transition_sample_fulfillment,
    set_influencer_blacklist,
    update_sample_fulfillment,
    update_outreach_task,
    update_outreach_target,
)


class Conflict(APIException):
    status_code = 409
    default_detail = "The resource changed or the idempotency key conflicts."
    default_code = "conflict"


CanResolveInfluencerRead = any_permission_class(
    "influencers.outreach.manage",
    "influencers.fulfillment.manage",
)
RESOLVE_READ_PERMISSION_CODES = (
    "influencers.outreach.manage",
    "influencers.fulfillment.manage",
)
BLACKLIST_PERMISSION_CODES = (
    "influencers.manage",
    "influencers.fulfillment.manage",
)


def _lock_influencer_write_tenant(user):
    return Tenant.objects.select_for_update().get(pk=user.tenant_id)


def _require_resolve_read_scope(user):
    for permission_code in RESOLVE_READ_PERMISSION_CODES:
        try:
            require_all_scope(user, permission_code)
        except PermissionDenied:
            continue
        return
    raise PermissionDenied(
        "This operation requires all-tenant data scope for an influencer resolve permission."
    )


def _require_blacklist_scope(user):
    for permission_code in BLACKLIST_PERMISSION_CODES:
        if not check_user_permission(user, permission_code):
            raise PermissionDenied(
                "Blacklist changes require profile and fulfillment manage permissions."
            )
        require_all_scope(user, permission_code)


def _pagination(request):
    try:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
    except ValueError as exc:
        raise ValidationError("Pagination values must be integers.") from exc
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValidationError("Invalid pagination range.")
    return page, page_size


def _expected_version(request):
    raw = request.headers.get("If-Match", "").strip().strip('"')
    if not raw.isdigit():
        raise ValidationError({"If-Match": "A numeric resource version is required."})
    return int(raw)


def _optional_expected_version(request):
    return _expected_version(request) if request.headers.get("If-Match") else None


def _assert_influencer_version(request, influencer):
    expected_updated_at = _expected_influencer_updated_at(request)
    if expected_updated_at != influencer.updated_at:
        raise Conflict({"If-Match": "Influencer was changed by another request."})


def _expected_influencer_updated_at(request):
    raw_version = request.headers.get("If-Match", "").strip().strip('"')
    expected_updated_at = parse_datetime(raw_version)
    if expected_updated_at is None:
        raise ValidationError({"If-Match": "The current updated_at timestamp is required."})
    return expected_updated_at


def _advance_influencer_version(influencer):
    updated_at = timezone.now()
    models.QuerySet.update(
        Influencer.objects.filter(pk=influencer.pk, tenant_id=influencer.tenant_id),
        updated_at=updated_at,
    )
    influencer.updated_at = updated_at


def _query_bool(value, *, field):
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValidationError({field: "Expected true or false."})


def _with_open_sample_statuses(queryset, *, tenant):
    """Annotate candidate profiles without leaking or scanning other tenants."""
    direct_samples = SampleFulfillment.objects.filter(
        tenant=tenant,
        is_deleted=False,
        influencer_id=OuterRef("pk"),
    )
    tiktok_identity_samples = SampleFulfillment.objects.filter(
        tenant=tenant,
        is_deleted=False,
        influencer__platform__iexact="TikTok",
        influencer__handle__iexact=OuterRef("handle"),
    )

    def status_exists(status):
        return Case(
            When(
                Q(platform__iexact="TikTok") & ~Q(handle=""),
                then=Exists(tiktok_identity_samples.filter(status=status)),
            ),
            default=Exists(direct_samples.filter(status=status)),
            output_field=BooleanField(),
        )

    return queryset.annotate(
        has_pending_sample=status_exists(SampleFulfillment.Status.PENDING),
        has_shipped_sample=status_exists(SampleFulfillment.Status.SHIPPED),
        has_overdue_sample=status_exists(SampleFulfillment.Status.OVERDUE),
    )


def _open_sample_statuses(influencer):
    return [
        status
        for status, attribute in (
            (SampleFulfillment.Status.PENDING, "has_pending_sample"),
            (SampleFulfillment.Status.SHIPPED, "has_shipped_sample"),
            (SampleFulfillment.Status.OVERDUE, "has_overdue_sample"),
        )
        if bool(getattr(influencer, attribute, False))
    ]


def _influencer_candidates(queryset, *, limit, include_handle=False):
    rows = []
    seen = set()
    for influencer in queryset.select_related("profile").order_by(
        "-is_blacklisted", "id"
    ).iterator(chunk_size=max(100, int(limit))):
        handle = str(influencer.handle or "").strip().lstrip("@").strip()
        key = (
            f"tiktok:{normalize_tiktok_username(handle)}"
            if str(influencer.platform or "").lower() == "tiktok" and handle
            else f"id:{influencer.pk}"
        )
        if key in seen:
            continue
        seen.add(key)
        profile = getattr(influencer, "profile", None)
        row = {
            "id": influencer.id, "code": influencer.code, "name": influencer.name,
            "display_name": getattr(profile, "display_name", "") or influencer.name,
            "platform": influencer.platform, "status": influencer.status,
            "is_blacklisted": bool(influencer.is_blacklisted),
            "open_sample_statuses": _open_sample_statuses(influencer),
        }
        if include_handle:
            row["handle"] = handle
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _resolve_existing_influencer(*, tenant, account, blacklist_subquery):
    """Find one tenant-scoped TikTok profile using normalized account text."""
    direct_blacklist_subquery = InfluencerRestriction.objects.filter(
        tenant=tenant,
        influencer_id=OuterRef("pk"),
        is_blacklisted=True,
    )
    candidates = list(
        Influencer.objects.select_for_update()
        .filter(
            tenant=tenant,
            platform__iexact="TikTok",
            handle__iexact=account,
        )
        .annotate(
            is_blacklisted=Exists(blacklist_subquery),
            direct_is_blacklisted=Exists(direct_blacklist_subquery),
        )
        .order_by("-direct_is_blacklisted", "-is_blacklisted", "id")
    )
    return candidates[0] if candidates else None


class InfluencerCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        blacklist_subquery = active_influencer_restriction_subquery(request.user.tenant)
        # Collection rows do not need contacts or audit history. Loading those
        # relations for every page made the 24k-profile library exceed the UI timeout.
        queryset = Influencer.objects.filter(tenant=request.user.tenant).select_related(
            "profile"
        ).annotate(_is_blacklisted=Exists(blacklist_subquery))
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            search_filter = (
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(profile__tenant=request.user.tenant, profile__display_name__icontains=search)
                | Q(profile__tenant=request.user.tenant, profile__external_influencer_id__icontains=search)
            )
            queryset = queryset.filter(search_filter)
        if status:
            queryset = queryset.filter(status=status)
        platform = request.query_params.get("platform", "").strip()
        if platform:
            queryset = queryset.filter(platform__iexact=platform)
        cooperation_status = request.query_params.get("cooperation_status", "").strip()
        if cooperation_status:
            queryset = queryset.filter(cooperation_status=cooperation_status)
        for field in ("level", "market", "tier"):
            value = request.query_params.get(field, "").strip()
            if value:
                queryset = queryset.filter(**{f"profile__tenant": request.user.tenant, f"profile__{field}__iexact": value})
        is_blacklisted = request.query_params.get("is_blacklisted", "").strip()
        if is_blacklisted:
            queryset = queryset.filter(_is_blacklisted=_query_bool(is_blacklisted, field="is_blacklisted"))
        ordering = request.query_params.get("ordering", "-updated_at").strip() or "-updated_at"
        allowed_ordering = {
            "updated_at", "-updated_at", "follower_count", "-follower_count", "name", "-name",
            "profile__display_name", "-profile__display_name", "profile__level", "-profile__level",
            "profile__tier", "-profile__tier", "profile__market", "-profile__market",
            "profile__average_video_views", "-profile__average_video_views",
            "profile__historical_gmv", "-profile__historical_gmv",
        }
        if ordering not in allowed_ordering:
            raise ValidationError({"ordering": "Unsupported ordering field."})
        queryset = queryset.order_by(ordering, "-id")
        page, page_size = _pagination(request)
        return success_response(paginated_data(
            request,
            queryset,
            InfluencerPublicSerializer,
            page=page,
            page_size=page_size,
            serializer_context={"request": request, "include_relations": False},
        ))

    @transaction.atomic
    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        _lock_influencer_write_tenant(request.user)
        serializer = InfluencerSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant=request.user.tenant)
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="influencers",
            action="create",
            object_type="influencer",
            object_id=instance.pk,
            after_data={"code": instance.code, "status": instance.status},
        )
        return success_response(InfluencerPublicSerializer(instance).data, status=201)


class InfluencerDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get_object(self, request, pk, *, include_relations=True):
        queryset = Influencer.objects.select_related("profile")
        if include_relations:
            queryset = queryset.prefetch_related("contacts", "restrict_events__actor")
        return get_object_or_404(queryset, pk=pk, tenant=request.user.tenant)

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        include_relations = _query_bool(
            request.query_params.get("include_relations", "true"),
            field="include_relations",
        )
        instance = self.get_object(request, pk, include_relations=include_relations)
        return success_response(InfluencerPublicSerializer(
            instance,
            context={"request": request, "include_relations": include_relations},
        ).data)

    @transaction.atomic
    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        _lock_influencer_write_tenant(request.user)
        writes_identity = bool({"handle", "platform"}.intersection(request.data))
        queryset = Influencer.objects if writes_identity else Influencer.objects.select_for_update()
        instance = get_object_or_404(queryset, pk=pk, tenant=request.user.tenant)
        before = {"code": instance.code, "status": instance.status}
        serializer = InfluencerSerializer(instance, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if writes_identity:
            instance = lock_influencer_identity_change(
                instance,
                platform=serializer.validated_data.get("platform", instance.platform),
                handle=serializer.validated_data.get("handle", instance.handle),
            )
            serializer = InfluencerSerializer(
                instance,
                data=request.data,
                partial=True,
                context={"request": request},
            )
            serializer.is_valid(raise_exception=True)
        _assert_influencer_version(request, instance)
        instance = serializer.save()
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="influencers",
            action="update",
            object_type="influencer",
            object_id=instance.pk,
            before_data=before,
            after_data={"code": instance.code, "status": instance.status},
        )
        return success_response(InfluencerPublicSerializer(instance).data)


class InfluencerStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    @transaction.atomic
    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        _lock_influencer_write_tenant(request.user)
        instance = get_object_or_404(Influencer.objects.select_for_update(), pk=pk, tenant=request.user.tenant)
        _assert_influencer_version(request, instance)
        status = request.data.get("status")
        if status not in Influencer.Status.values:
            raise ValidationError({"status": "Status must be active or inactive."})
        before = instance.status
        instance.status = status
        instance.save(update_fields=["status", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="influencers",
            action="status_change",
            object_type="influencer",
            object_id=instance.pk,
            before_data={"status": before},
            after_data={"status": status},
        )
        return success_response(InfluencerPublicSerializer(instance).data)


class InfluencerContactsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        influencer = get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)
        rows = influencer.contacts.filter(tenant=request.user.tenant, is_active=True).order_by("-is_primary", "id")
        return success_response(InfluencerContactSerializer(rows, many=True).data)

    @transaction.atomic
    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        _lock_influencer_write_tenant(request.user)
        influencer = get_object_or_404(Influencer.objects.select_for_update(), pk=pk, tenant=request.user.tenant)
        _assert_influencer_version(request, influencer)
        payload = request.data.get("contacts", [])
        if not isinstance(payload, list):
            raise ValidationError({"contacts": "Must be a list."})
        serializers = [InfluencerContactSerializer(data=item) for item in payload]
        for serializer in serializers:
            serializer.is_valid(raise_exception=True)
        existing = {
            (row.channel, row.value): row
            for row in influencer.contacts.filter(tenant=request.user.tenant)
        }
        # Contact rows use the protected tenant-owned manager.  This endpoint
        # has already validated the complete replacement payload and holds the
        # tenant/influencer locks, so use the explicit low-level update here
        # instead of bypassing validation through the default manager.
        models.QuerySet.update(
            influencer.contacts.filter(tenant=request.user.tenant),
            is_active=False,
            is_primary=False,
        )
        created = []
        for serializer in serializers:
            values = serializer.validated_data
            row = existing.get((values["channel"], values["value"]))
            if row is None:
                row = serializer.save(tenant=request.user.tenant, influencer=influencer, created_by=request.user)
            else:
                row.label = values.get("label", "")
                row.is_primary = values.get("is_primary", False)
                row.is_active = values.get("is_active", True)
                row.full_clean()
                row.save(update_fields=["label", "is_primary", "is_active", "updated_at"])
            created.append(row)
        _advance_influencer_version(influencer)
        return success_response(InfluencerContactSerializer(created, many=True).data)


class InfluencerBlacklistView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "influencers.manage"

    def post(self, request, pk):
        _require_blacklist_scope(request.user)
        influencer = get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)
        blacklisted = request.data.get("is_blacklisted", request.data.get("blacklisted", True))
        if not isinstance(blacklisted, bool):
            raise ValidationError({"is_blacklisted": "Expected a JSON boolean."})
        reason = str(request.data.get("reason", "")).strip()
        restriction, event = set_influencer_blacklist(
            user=request.user, influencer=influencer, blacklisted=blacklisted, reason=reason
        )
        return success_response({"is_blacklisted": restriction.is_blacklisted, "event": InfluencerRestrictEventSerializer(event).data})


class InfluencerBlacklistHistoryView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        influencer = get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)
        rows = influencer.restrict_events.filter(tenant=request.user.tenant).select_related("actor").order_by("-occurred_at", "-id")[:100]
        return success_response(InfluencerRestrictEventSerializer(rows, many=True).data)


class InfluencerResolveView(APIView):
    """Resolve creator accounts without exposing cross-tenant profile data."""

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.manage"
    write_permission_code = "influencers.fulfillment.manage"

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [CanResolveInfluencerRead()]
        return super().get_permissions()

    def get(self, request):
        _require_resolve_read_scope(request.user)
        raw_query = str(
            request.query_params.get("q")
            or request.query_params.get("search")
            or request.query_params.get("handle")
            or request.query_params.get("code")
            or request.query_params.get("name")
            or ""
        ).strip()
        query = normalize_tiktok_username(raw_query)
        blacklist_subquery = active_influencer_restriction_subquery(request.user.tenant)
        queryset = _with_open_sample_statuses(Influencer.objects.filter(
            tenant=request.user.tenant,
            platform__iexact="TikTok",
            status=Influencer.Status.ACTIVE,
        ).annotate(is_blacklisted=Exists(blacklist_subquery)), tenant=request.user.tenant)
        if query and is_valid_tiktok_username(query):
            queryset = queryset.filter(handle__icontains=query)
        rows = _influencer_candidates(queryset, limit=50, include_handle=True)
        return success_response({"query": query, "candidates": rows, "results": rows})

    @transaction.atomic
    def post(self, request):
        """Resolve an exact account or create the minimal tenant profile needed for sampling."""
        require_all_scope(request.user, self.write_permission_code)
        _lock_influencer_write_tenant(request.user)
        account = normalize_tiktok_username(
            request.data.get("handle") or request.data.get("account") or ""
        )
        if not account or not is_valid_tiktok_username(account):
            raise ValidationError({
                "handle": "TikTok username may contain only letters, numbers, periods, and underscores.",
            })

        blacklist_subquery = active_influencer_restriction_subquery(request.user.tenant)
        influencer = _resolve_existing_influencer(
            tenant=request.user.tenant,
            account=account,
            blacklist_subquery=blacklist_subquery,
        )
        created = False
        if influencer is None:
            digest = hashlib.sha256(
                f"{request.user.tenant_id}:{account}".encode("utf-8")
            ).hexdigest()[:20]
            base_code = f"tk-{digest}"
            for suffix in range(100):
                code = base_code if suffix == 0 else f"{base_code[:72]}-{suffix}"
                try:
                    with transaction.atomic():
                        candidate, candidate_created = Influencer.objects.get_or_create(
                            tenant=request.user.tenant,
                            code=code,
                            defaults={
                                "name": account,
                                "handle": account,
                                "platform": "TikTok",
                                "status": Influencer.Status.ACTIVE,
                            },
                        )
                except IntegrityError:
                    continue
                candidate_values = normalize_tiktok_username(candidate.handle)
                if candidate_created or (
                    candidate.platform.lower() == "tiktok" and candidate_values == account
                ):
                    influencer, created = candidate, candidate_created
                    break
            else:
                raise ValidationError({"handle": "Unable to allocate a tenant-scoped influencer profile."})
            if created:
                write_operation_log(
                    tenant=request.user.tenant,
                    user=request.user,
                    module="influencers",
                    action="create_from_fulfillment",
                    object_type="influencer",
                    object_id=influencer.pk,
                    after_data={"code": influencer.code, "handle": influencer.handle},
                )

        is_blacklisted = influencer_has_active_restriction(influencer)
        resolved_influencer = _with_open_sample_statuses(
            Influencer.objects.filter(pk=influencer.pk, tenant=request.user.tenant),
            tenant=request.user.tenant,
        ).get()
        payload = {
            "id": influencer.id,
            "code": influencer.code,
            "name": influencer.name,
            "handle": influencer.handle,
            "platform": influencer.platform,
            "status": influencer.status,
            "is_blacklisted": is_blacklisted,
            "open_sample_statuses": _open_sample_statuses(resolved_influencer),
            "created": created,
        }
        return success_response(payload, status=201 if created else 200)


class OutreachTaskCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        active_samples = Prefetch(
            "sample_fulfillments",
            queryset=SampleFulfillment.objects.filter(
                tenant=request.user.tenant,
                is_deleted=False,
            ).select_related("influencer").prefetch_related(
                Prefetch(
                    "video_results",
                    queryset=VideoResult.objects.filter(
                        tenant=request.user.tenant,
                        published_at__isnull=False,
                    ),
                    to_attr="_published_video_results",
                )
            ),
            to_attr="_active_samples",
        )
        active_targets = Prefetch(
            "targets",
            queryset=OutreachTarget.objects.filter(
                tenant=request.user.tenant,
                is_deleted=False,
            ).select_related("influencer"),
            to_attr="_active_targets",
        )
        queryset = OutreachTask.objects.filter(
            tenant=request.user.tenant,
        ).select_related("influencer", "store", "owner", "dispatcher", "spu").prefetch_related(
            active_samples,
            active_targets,
        )
        if "deleted_only" in request.query_params and "include_deleted" in request.query_params:
            raise ValidationError({"detail": "deleted_only and include_deleted cannot be used together."})
        deleted_only = _query_bool(request.query_params.get("deleted_only", "false"), field="deleted_only")
        include_deleted = _query_bool(request.query_params.get("include_deleted", "false"), field="include_deleted")
        if deleted_only:
            queryset = queryset.filter(is_deleted=True)
        elif not include_deleted:
            queryset = queryset.filter(is_deleted=False)
        status = request.query_params.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        store_id = request.query_params.get("store", "").strip()
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(task_no__icontains=search)
                | Q(task_name__icontains=search)
                | Q(store__name__icontains=search)
                | Q(external_product_id__icontains=search)
                | Q(sku_prefix__icontains=search)
                | Q(owner__full_name__icontains=search)
                | Q(owner__username__icontains=search)
            )
        queryset = queryset.order_by("-created_at", "-id")
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, OutreachTaskSerializer, page=page, page_size=page_size))

    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        serializer = OutreachTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            task = create_outreach_task(user=request.user, validated_data=serializer.validated_data)
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTaskSerializer(task).data, status=201)


class OutreachTaskOptionsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        raw_include_influencers = request.query_params.get("include_influencers")
        include_influencers = (
            True
            if raw_include_influencers is None
            else _query_bool(raw_include_influencers, field="include_influencers")
        )
        stores = StoreMaster.objects.filter(
            tenant=request.user.tenant,
            status=StatusChoices.ACTIVE,
        ).select_related("platform").order_by("name", "code")
        bd_users = CustomUser.objects.filter(
            tenant=request.user.tenant,
            user_type=CustomUser.UserType.INTERNAL,
            is_active=True,
            user_roles__tenant=request.user.tenant,
            user_roles__role__tenant=request.user.tenant,
            user_roles__role__code="bd",
            user_roles__role__status="active",
        ).distinct().order_by("full_name", "username")[:200]
        stores = stores[:200]
        payload = {
            "stores": [
                {
                    "id": store.id,
                    "name": store.name,
                    "code": store.code,
                    "country_code": store.country_code,
                    "platform_name": store.platform.name,
                }
                for store in stores
            ],
            "bd_users": [
                {"id": user.id, "username": user.username, "full_name": user.full_name}
                for user in bd_users
            ],
        }
        if include_influencers:
            blacklist_subquery = active_influencer_restriction_subquery(request.user.tenant)
            influencers = _with_open_sample_statuses(Influencer.objects.filter(
                tenant=request.user.tenant,
                status=Influencer.Status.ACTIVE,
            ).annotate(is_blacklisted=Exists(blacklist_subquery)), tenant=request.user.tenant)
            candidates = _influencer_candidates(
                influencers,
                limit=500,
                include_handle=check_user_permission(
                    request.user,
                    "influencers.fulfillment.manage",
                ),
            )
            if not check_user_permission(request.user, "influencers.fulfillment.manage"):
                candidates = [
                    {
                        key: candidate[key]
                        for key in ("id", "code", "name", "platform")
                    }
                    for candidate in candidates
                ]
            payload["influencers"] = candidates
        return success_response(payload)


class SampleFulfillmentOptionsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        search = request.query_params.get("search", "").strip()
        blacklist_subquery = active_influencer_restriction_subquery(request.user.tenant)
        influencers = _with_open_sample_statuses(Influencer.objects.filter(
            tenant=request.user.tenant,
            status=Influencer.Status.ACTIVE,
        ).annotate(is_blacklisted=Exists(blacklist_subquery)), tenant=request.user.tenant)
        normalized_search = normalize_tiktok_username(search)
        if search:
            if is_valid_tiktok_username(normalized_search):
                influencers = influencers.filter(handle__icontains=normalized_search)
            else:
                influencers = influencers.none()
        tasks = OutreachTask.objects.filter(
            tenant=request.user.tenant,
            is_deleted=False,
            status__in=(OutreachTask.Status.PENDING, OutreachTask.Status.IN_PROGRESS),
        ).select_related("store").order_by("-dispatch_time", "-id")[:200]
        return success_response({
            "tasks": [
                {
                    "id": task.id,
                    "task_no": task.task_no,
                    "task_name": task.task_name,
                    "store": task.store_id,
                    "store_name": task.store.name,
                    "product_name_snapshot": task.product_name_snapshot,
                    "external_product_id": task.external_product_id,
                    "sku_prefix": task.sku_prefix,
                    "status": task.status,
                }
                for task in tasks
            ],
            "influencers": _influencer_candidates(influencers, limit=100, include_handle=True),
        })


class OutreachProductMatchView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        product_id = request.query_params.get("product_id", "").strip()
        if not product_id:
            raise ValidationError({"product_id": "Product ID is required."})
        base_queryset = StoreProductListing.objects.filter(
            tenant=request.user.tenant,
            external_product_id=product_id,
            store__status=StatusChoices.ACTIVE,
        )
        store_ids = list(base_queryset.order_by("store_id").values_list("store_id", flat=True).distinct()[:201])
        truncated = len(store_ids) > 200
        store_ids = store_ids[:200]
        listings = base_queryset.filter(store_id__in=store_ids).select_related(
            "store", "store__platform"
        ).prefetch_related("sku_prices").order_by("store__name", "id")
        grouped = {}
        for listing in listings:
            prefixes = {listing.parent_sku.strip()} if listing.parent_sku.strip() else set()
            prefixes.update(
                price.external_sku.split("-", 1)[0]
                for price in listing.sku_prices.all()
                if price.external_sku
            )
            candidate = grouped.setdefault(listing.store_id, {
                "store_id": listing.store_id,
                "store_name": listing.store.name,
                "store_code": listing.store.code,
                "country_code": listing.store.country_code,
                "product_name": listing.product_name,
                "sku_prefixes": set(),
            })
            candidate["sku_prefixes"].update(prefix for prefix in prefixes if prefix)
        candidates = [
            {**candidate, "sku_prefixes": sorted(candidate["sku_prefixes"])}
            for candidate in grouped.values()
        ]
        return success_response({
            "product_id": product_id,
            "matched": bool(candidates),
            "unique": len(candidates) == 1 and not truncated,
            "truncated": truncated,
            "reason": "" if candidates else "data_source_not_imported",
            "candidates": candidates,
        })


class OutreachTaskDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        filters = {"tenant": request.user.tenant, "pk": pk}
        if request.query_params.get("include_deleted", "").lower() not in {"1", "true", "yes"}:
            filters["is_deleted"] = False
        task = get_object_or_404(OutreachTask, **filters)
        return success_response(OutreachTaskSerializer(task).data)

    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        task = get_object_or_404(
            OutreachTask,
            tenant=request.user.tenant,
            pk=pk,
            is_deleted=False,
        )
        serializer = OutreachTaskUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            task = update_outreach_task(
                user=request.user,
                task=task,
                validated_data=serializer.validated_data,
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTaskSerializer(task).data)

    def delete(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        task = get_object_or_404(
            OutreachTask, tenant=request.user.tenant, pk=pk, is_deleted=False
        )
        try:
            task = soft_delete_outreach_task(
                user=request.user,
                task=task,
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTaskSerializer(task).data)


class OutreachTaskRestoreView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        task = get_object_or_404(
            OutreachTask, tenant=request.user.tenant, pk=pk, is_deleted=True
        )
        try:
            task = restore_outreach_task(
                user=request.user,
                task=task,
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTaskSerializer(task).data)


class OutreachTaskProgressView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        return success_response(
            outreach_task_progress(
                user=request.user,
                task=get_object_or_404(
                    OutreachTask,
                    tenant=request.user.tenant,
                    pk=pk,
                    is_deleted=False,
                ),
            )
        )


class OutreachTargetCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def _task(self, request, pk):
        return get_object_or_404(
            OutreachTask,
            tenant=request.user.tenant,
            pk=pk,
            is_deleted=False,
        )

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        task = self._task(request, pk)
        queryset = OutreachTarget.objects.filter(
            tenant=request.user.tenant,
            task=task,
            is_deleted=False,
        ).select_related("influencer", "influencer__profile")
        page, page_size = _pagination(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                OutreachTargetSerializer,
                page=page,
                page_size=page_size,
            )
        )

    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        task = self._task(request, pk)
        serializer = OutreachTargetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target, created = add_outreach_target(
                user=request.user,
                task=task,
                influencer=serializer.validated_data["influencer"],
                notes=serializer.validated_data.get("notes", ""),
                expected_version=_optional_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTargetSerializer(target).data, status=201 if created else 200)


class OutreachTargetDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def _target(self, request, task_pk, target_pk):
        return get_object_or_404(
            OutreachTarget,
            tenant=request.user.tenant,
            task_id=task_pk,
            pk=target_pk,
            task__is_deleted=False,
            is_deleted=False,
        )

    def patch(self, request, task_pk, target_pk):
        require_all_scope(request.user, self.write_permission_code)
        target = self._target(request, task_pk, target_pk)
        serializer = OutreachTargetSerializer(target, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            target = update_outreach_target(
                user=request.user,
                task=task_pk,
                target=target,
                expected_version=_expected_version(request),
                outreach_result=serializer.validated_data.get("outreach_result"),
                notes=serializer.validated_data.get("notes"),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTargetSerializer(target).data)

    def delete(self, request, task_pk, target_pk):
        require_all_scope(request.user, self.write_permission_code)
        target = self._target(request, task_pk, target_pk)
        try:
            target = soft_delete_outreach_target(
                user=request.user,
                task=task_pk,
                target=target,
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTargetSerializer(target).data)


class OutreachTaskStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        task = get_object_or_404(
            OutreachTask, tenant=request.user.tenant, pk=pk, is_deleted=False
        )
        try:
            task = transition_outreach_task(
                user=request.user,
                task=task,
                status=request.data.get("status", ""),
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if exc.get_codes() == {"version": "conflict"}:
                raise Conflict(exc.detail) from exc
            raise
        return success_response(OutreachTaskSerializer(task).data)


class SampleFulfillmentCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.view"
    write_permission_code = "influencers.fulfillment.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        queryset = SampleFulfillment.objects.filter(tenant=request.user.tenant).select_related(
            "outreach_task", "influencer", "influencer__profile", "store", "owner", "deleted_by"
        ).prefetch_related(
            "items",
            Prefetch(
                "video_results",
                queryset=VideoResult.objects.filter(
                    tenant=request.user.tenant,
                    published_at__isnull=False,
                ).order_by("-published_at", "-id"),
                to_attr="_published_video_results",
            ),
        )
        if "deleted_only" in request.query_params and "include_deleted" in request.query_params:
            raise ValidationError({"detail": "deleted_only and include_deleted cannot be used together."})
        deleted_only = _query_bool(request.query_params.get("deleted_only", "false"), field="deleted_only")
        include_deleted = _query_bool(request.query_params.get("include_deleted", "false"), field="include_deleted")
        if deleted_only:
            queryset = queryset.filter(is_deleted=True)
        elif not include_deleted:
            queryset = queryset.filter(is_deleted=False)
        status = request.query_params.get("status", "").strip()
        if status:
            if status not in SampleFulfillment.Status.values:
                raise ValidationError({"status": "Unsupported fulfillment status."})
            queryset = queryset.filter(status=status)
        outreach_task_id = request.query_params.get("outreach_task", "").strip()
        if outreach_task_id:
            if not outreach_task_id.isdigit() or int(outreach_task_id) < 1:
                raise ValidationError({"outreach_task": "outreach_task must be a positive integer."})
            queryset = queryset.filter(
                outreach_task_id=int(outreach_task_id),
                outreach_task__tenant=request.user.tenant,
            )
        store_id = request.query_params.get("store", "").strip()
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        search = request.query_params.get("search", "").strip()
        if search:
            search_filter = (
                Q(fulfillment_no__icontains=search)
                | Q(outreach_task__task_no__icontains=search)
                | Q(outreach_task__task_name__icontains=search)
                | Q(influencer__name__icontains=search)
                | Q(store__name__icontains=search)
                | Q(product_name_snapshot__icontains=search)
                | Q(external_product_id__icontains=search)
                | Q(sample_order_no__icontains=search)
            )
            normalized_handle = normalize_tiktok_username(search)
            if is_valid_tiktok_username(normalized_handle):
                search_filter |= Q(influencer__handle__icontains=normalized_handle)
            queryset = queryset.filter(search_filter)
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, SampleFulfillmentSerializer, page=page, page_size=page_size))

    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        request_key = request.headers.get("Idempotency-Key", "").strip()
        if not request_key:
            raise ValidationError({"Idempotency-Key": "This header is required."})
        serializer = SampleFulfillmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = dict(serializer.validated_data)
        items = validated_data.pop("items", [])
        try:
            fulfillment, created = create_sample_fulfillment(
                user=request.user,
                request_key=request_key,
                validated_data=validated_data,
                item_payloads=items,
            )
        except ValidationError as exc:
            if (
                {"idempotency_key", "fulfillment_no"}.intersection(exc.detail)
                or "conflict" in str(exc.get_codes())
            ):
                raise Conflict(exc.detail) from exc
            raise
        fulfillment = SampleFulfillment.objects.prefetch_related("items").get(pk=fulfillment.pk)
        return success_response(
            SampleFulfillmentSerializer(fulfillment).data,
            status=201 if created else 200,
        )


class SampleFulfillmentDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.view"
    write_permission_code = "influencers.fulfillment.manage"

    def _get(self, request, pk, *, include_deleted=False):
        filters = {"tenant": request.user.tenant, "pk": pk}
        if not include_deleted:
            filters["is_deleted"] = False
        return get_object_or_404(
            SampleFulfillment.objects.select_related(
                "outreach_task", "influencer", "store", "owner", "deleted_by"
            ).prefetch_related(
                "items",
                Prefetch(
                    "video_results",
                    queryset=VideoResult.objects.filter(
                        tenant=request.user.tenant,
                        published_at__isnull=False,
                    ).order_by("-published_at", "-id"),
                    to_attr="_published_video_results",
                ),
            ),
            **filters,
        )

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        include_deleted = request.query_params.get("include_deleted", "").lower() in {
            "1", "true", "yes"
        }
        fulfillment = self._get(request, pk, include_deleted=include_deleted)
        # Detail reads use the redacted contract; pricing snapshots are only
        # returned from an explicitly authorized write response.
        return success_response(SampleFulfillmentSerializer(fulfillment).data)

    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        fulfillment = self._get(request, pk)
        initial_status = fulfillment.status
        serializer = SampleFulfillmentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)
        requested_status = validated.pop("status", None)
        confirm_terminal = validated.pop("confirm_terminal", False)
        item_payloads = validated.pop("items", None)
        append_item_payloads = validated.pop("append_items", None)
        items_mode = validated.pop("items_mode", "replace")
        expected_version = _expected_version(request)
        has_fact_changes = bool(validated) or item_payloads is not None or append_item_payloads is not None
        try:
            with transaction.atomic():
                if has_fact_changes:
                    fulfillment = update_sample_fulfillment(
                        user=request.user,
                        fulfillment=fulfillment,
                        expected_version=expected_version,
                        validated_data=validated,
                        item_payloads=item_payloads,
                        append_item_payloads=append_item_payloads,
                        items_mode=items_mode,
                    )
                if requested_status and requested_status != initial_status:
                    fulfillment = transition_sample_fulfillment(
                        user=request.user,
                        fulfillment=fulfillment,
                        status=requested_status,
                        expected_version=fulfillment.version,
                        reason="manual_edit",
                        confirm_terminal=confirm_terminal,
                    )
                elif not has_fact_changes and not requested_status:
                    raise ValidationError(
                        {"detail": "At least one editable fulfillment field is required."}
                    )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        fulfillment = self._get(request, pk)
        return success_response(SampleFulfillmentSerializer(fulfillment).data)

    def delete(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        fulfillment = self._get(request, pk)
        try:
            fulfillment = soft_delete_sample_fulfillment(
                user=request.user,
                fulfillment=fulfillment,
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        return success_response(SampleFulfillmentSerializer(fulfillment).data)


class SampleFulfillmentRestoreView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.view"
    write_permission_code = "influencers.fulfillment.manage"

    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        fulfillment = get_object_or_404(
            SampleFulfillment,
            tenant=request.user.tenant,
            pk=pk,
            is_deleted=True,
        )
        try:
            fulfillment = restore_sample_fulfillment(
                user=request.user,
                fulfillment=fulfillment,
                expected_version=_expected_version(request),
            )
        except ValidationError as exc:
            if "conflict" in str(exc.get_codes()):
                raise Conflict(exc.detail) from exc
            raise
        fulfillment = SampleFulfillment.objects.select_related(
            "outreach_task", "influencer", "store", "owner", "deleted_by"
        ).prefetch_related(
            "items",
            Prefetch(
                "video_results",
                queryset=VideoResult.objects.filter(
                    tenant=request.user.tenant,
                    published_at__isnull=False,
                ).order_by("-published_at", "-id"),
                to_attr="_published_video_results",
            ),
        ).get(pk=fulfillment.pk, tenant=request.user.tenant)
        return success_response(SampleFulfillmentSerializer(fulfillment).data)


class SampleFulfillmentStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.view"
    write_permission_code = "influencers.fulfillment.manage"

    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        requested_status = request.data.get("status", "")
        if requested_status not in {
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        }:
            raise ValidationError(
                {"status": "Manual status changes only support completed or cancelled."}
            )
        fulfillment = get_object_or_404(
            SampleFulfillment, tenant=request.user.tenant, pk=pk, is_deleted=False
        )
        confirm_terminal = request.data.get("confirm_terminal", False)
        if not isinstance(confirm_terminal, bool):
            raise ValidationError({"confirm_terminal": "confirm_terminal must be a boolean."})
        try:
            fulfillment = transition_sample_fulfillment(
                user=request.user,
                fulfillment=fulfillment,
                status=requested_status,
                expected_version=_expected_version(request),
                reason=request.data.get("reason", ""),
                confirm_terminal=confirm_terminal,
            )
        except ValidationError as exc:
            if exc.get_codes() == {"version": "conflict"}:
                raise Conflict(exc.detail) from exc
            raise
        return success_response(SampleFulfillmentSerializer(fulfillment).data)


class ProductPriceLookupView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.catalog.view"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        store_id = request.query_params.get("store_id", "").strip()
        site_code = request.query_params.get("site_code", "").strip()
        sku = request.query_params.get("sku", "").strip()
        product_id = request.query_params.get("product_id", "").strip()
        if not store_id.isdigit() or not site_code or not (sku or product_id):
            raise ValidationError("store_id, site_code and either sku or product_id are required.")
        queryset = SkuPriceSnapshot.objects.select_related("listing", "listing__store").filter(
            tenant=request.user.tenant,
            listing__store_id=int(store_id),
            listing__site_code=site_code,
        )
        if sku:
            queryset = queryset.filter(external_sku__iexact=sku)
        if product_id:
            queryset = queryset.filter(listing__external_product_id=product_id)
        rows = list(queryset.order_by("external_sku", "variant_id", "-source_updated_at", "-id"))
        if not rows:
            return success_response({"matched": False, "reason": "data_source_not_imported", "results": []})
        return success_response({"matched": True, "reason": "", "results": SkuPriceSnapshotSerializer(rows, many=True).data})


class BdPerformanceView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        fulfillment_permission = "influencers.fulfillment.view"
        if not check_user_permission(request.user, fulfillment_permission):
            raise PermissionDenied("Both outreach and fulfillment view permissions are required.")
        require_all_scope(request.user, fulfillment_permission)

        default_start, default_end = default_performance_dates(tenant=request.user.tenant)
        start_date = parse_performance_date(
            request.query_params.get("start_date") or default_start.isoformat(),
            field="start_date",
        )
        end_date = parse_performance_date(
            request.query_params.get("end_date") or default_end.isoformat(),
            field="end_date",
        )
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        max_data_time = AffiliateOrderSnapshot.objects.filter(tenant=request.user.tenant).aggregate(
            max_data_time=Max("data_time")
        )["max_data_time"]
        max_date = timezone.localtime(max_data_time).date() if max_data_time else None
        latest_allowed = min(yesterday, max_date) if max_date else yesterday
        if end_date > latest_allowed:
            raise ValidationError({"end_date": "end_date must not exceed yesterday or the imported order date."})
        if start_date > end_date:
            raise ValidationError({"date": "start_date must not be after end_date."})
        if (end_date - start_date).days > 30:
            raise ValidationError({"date": "The date range must not exceed 31 days."})
        payload = build_bd_performance(
            tenant=request.user.tenant,
            start_date=start_date,
            end_date=end_date,
            attribution=(request.query_params.get("attribution") or "strict").strip().lower(),
            currency=(request.query_params.get("currency") or "CNY").strip().upper(),
        )
        return success_response(payload)


class BdPerformanceExportView(APIView):
    """Export only the already-authorized aggregate, never raw affiliate facts."""

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"

    def get(self, request):
        response = BdPerformanceView().get(request)
        payload = response.data["data"]
        output = StringIO(newline="")
        writer = csv.writer(output)
        columns = (
            "owner_id", "owner", "username", "outreach_tasks", "linked_count",
            "samples", "shipped_samples", "investment", "valid_orders",
            "quantity", "gmv", "commission", "roi",
        )
        writer.writerow(columns)
        for row in payload.get("rows", []):
            values = []
            for column in columns:
                value = row.get(column, "")
                value = "" if value is None else str(value)
                if value[:1] in {"=", "+", "-", "@"}:
                    value = "'" + value
                values.append(value)
            writer.writerow(values)
        writer.writerow(["TOTAL", "", ""] + [payload.get("totals", {}).get(column, "") for column in columns[3:]])
        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="bd-performance.csv"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "no-store"
        return response


class BdPerformanceDiagnosticView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"

    def get(self, request):
        response = BdPerformanceView().get(request)
        payload = response.data["data"]
        return success_response(payload.get("zero_gmv_diagnostic", {
            "is_zero_gmv": payload.get("totals", {}).get("gmv") == "0.0000",
            "reason_codes": [],
            "missing_exchange_rates": payload.get("missing_exchange_rates", []),
        }))
