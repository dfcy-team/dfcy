import csv
import hashlib
from io import StringIO
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Exists, Max, OuterRef, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.accounts.models import CustomUser
from apps.common.responses import paginated_data, success_response
from apps.masterdata.models import StatusChoices, StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import require_all_scope

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
)
from .serializers import (
    InfluencerSerializer,
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
    update_sample_fulfillment,
    update_outreach_task,
    update_outreach_target,
)


class Conflict(APIException):
    status_code = 409
    default_detail = "The resource changed or the idempotency key conflicts."
    default_code = "conflict"


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


def _query_bool(value, *, field):
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValidationError({field: "Expected true or false."})


class InfluencerCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        blacklist_subquery = InfluencerRestriction.objects.filter(
            tenant=request.user.tenant,
            influencer_id=OuterRef("pk"),
            is_blacklisted=True,
        )
        queryset = Influencer.objects.filter(tenant=request.user.tenant).select_related("profile").prefetch_related(
            Prefetch("restrictions", to_attr="_restriction_rows"),
            Prefetch("restrict_events", queryset=InfluencerRestrictEvent.objects.order_by("-occurred_at", "-id"), to_attr="_restriction_events"),
            "contacts",
        ).annotate(_is_blacklisted=Exists(blacklist_subquery))
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(profile__tenant=request.user.tenant, profile__display_name__icontains=search)
                | Q(profile__tenant=request.user.tenant, profile__external_influencer_id__icontains=search)
            )
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
        }
        if ordering not in allowed_ordering:
            raise ValidationError({"ordering": "Unsupported ordering field."})
        queryset = queryset.order_by(ordering, "-id")
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, InfluencerSerializer, page=page, page_size=page_size))

    @transaction.atomic
    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
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
        return success_response(InfluencerSerializer(instance).data, status=201)


class InfluencerDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get_object(self, request, pk):
        return get_object_or_404(
            Influencer.objects.select_related("profile").prefetch_related("contacts", "restrict_events__actor"),
            pk=pk,
            tenant=request.user.tenant,
        )

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        return success_response(InfluencerSerializer(self.get_object(request, pk)).data)

    @transaction.atomic
    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        instance = get_object_or_404(Influencer.objects.select_for_update(), pk=pk, tenant=request.user.tenant)
        before = {"code": instance.code, "status": instance.status}
        serializer = InfluencerSerializer(instance, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
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
        return success_response(InfluencerSerializer(instance).data)


class InfluencerStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    @transaction.atomic
    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        instance = get_object_or_404(Influencer.objects.select_for_update(), pk=pk, tenant=request.user.tenant)
        raw_version = request.headers.get("If-Match", "").strip().strip('"')
        expected_updated_at = parse_datetime(raw_version)
        if expected_updated_at is None:
            raise ValidationError({"If-Match": "The current updated_at timestamp is required."})
        if expected_updated_at != instance.updated_at:
            raise Conflict({"If-Match": "Influencer was changed by another request."})
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
        return success_response(InfluencerSerializer(instance).data)


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
        influencer = get_object_or_404(Influencer.objects.select_for_update(), pk=pk, tenant=request.user.tenant)
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
        influencer.contacts.filter(tenant=request.user.tenant).update(is_active=False, is_primary=False)
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
        return success_response(InfluencerContactSerializer(created, many=True).data)


class InfluencerBlacklistView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "influencers.manage"

    @transaction.atomic
    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        influencer = get_object_or_404(Influencer.objects.select_for_update(), pk=pk, tenant=request.user.tenant)
        blacklisted = bool(request.data.get("is_blacklisted", request.data.get("blacklisted", True)))
        reason = str(request.data.get("reason", "")).strip()
        restriction, _ = InfluencerRestriction.objects.update_or_create(
            tenant=request.user.tenant,
            influencer=influencer,
            defaults={"is_blacklisted": blacklisted, "reason": reason, "created_by": request.user},
        )
        action = InfluencerRestrictEvent.Action.BLACKLIST if blacklisted else InfluencerRestrictEvent.Action.UNBLACKLIST
        event = InfluencerRestrictEvent.objects.create(
            tenant=request.user.tenant, influencer=influencer, action=action,
            reason=reason or ("Manual blacklist" if blacklisted else "Manual unblacklist"), actor=request.user,
        )
        return success_response({"is_blacklisted": restriction.is_blacklisted, "event": InfluencerRestrictEventSerializer(event).data})


class InfluencerBlacklistHistoryView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"

    def get(self, request, pk):
        require_all_scope(request.user, self.read_permission_code)
        influencer = get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)
        rows = influencer.restrict_events.filter(tenant=request.user.tenant).select_related("actor").order_by("-occurred_at", "-id")
        return success_response(InfluencerRestrictEventSerializer(rows, many=True).data)


INFLUENCER_RESOLVE_PERMISSION_CODES = (
    "influencers.fulfillment.manage",
    "influencers.outreach.manage",
)
INFLUENCER_RESOLVE_WRITE_PERMISSION_CODES = (
    "influencers.fulfillment.manage",
)


def require_influencer_resolve_scope(user, permission_codes=INFLUENCER_RESOLVE_PERMISSION_CODES):
    for permission_code in permission_codes:
        if not check_user_permission(user, permission_code):
            continue
        try:
            require_all_scope(user, permission_code)
            return
        except PermissionDenied:
            continue
    raise PermissionDenied("Creator resolution requires fulfillment or outreach management scope.")


class InfluencerResolvePermission(DeclaredApplicationPermission):
    def has_permission(self, request, view):
        user = request.user
        if not (
            user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
        ):
            return False
        try:
            permission_codes = (
                INFLUENCER_RESOLVE_WRITE_PERMISSION_CODES
                if request.method == "POST"
                else INFLUENCER_RESOLVE_PERMISSION_CODES
            )
            require_influencer_resolve_scope(user, permission_codes)
            return True
        except PermissionDenied:
            return False


class InfluencerResolveView(APIView):
    """Resolve creator accounts without exposing cross-tenant profile data."""

    permission_classes = [InfluencerResolvePermission]

    def get(self, request):
        require_influencer_resolve_scope(request.user)
        query = str(
            request.query_params.get("q")
            or request.query_params.get("search")
            or request.query_params.get("handle")
            or request.query_params.get("code")
            or request.query_params.get("name")
            or ""
        ).strip()
        blacklist_subquery = InfluencerRestriction.objects.filter(
            tenant=request.user.tenant,
            influencer_id=OuterRef("pk"),
            is_blacklisted=True,
        )
        queryset = Influencer.objects.filter(
            tenant=request.user.tenant,
            status=Influencer.Status.ACTIVE,
        ).annotate(is_blacklisted=Exists(blacklist_subquery))
        if query:
            queryset = queryset.filter(
                Q(handle__icontains=query)
                | Q(code__icontains=query)
                | Q(name__icontains=query)
            )
        rows = []
        for influencer in queryset.order_by("name", "code")[:50]:
            rows.append(
                {
                    "id": influencer.id,
                    "code": influencer.code,
                    "name": influencer.name,
                    "handle": influencer.handle,
                    "platform": influencer.platform,
                    "status": influencer.status,
                    "is_blacklisted": influencer.is_blacklisted,
                }
            )
        return success_response({"query": query, "candidates": rows, "results": rows})

    @transaction.atomic
    def post(self, request):
        """Resolve an exact account or create the minimal tenant profile needed for sampling."""
        require_influencer_resolve_scope(
            request.user,
            INFLUENCER_RESOLVE_WRITE_PERMISSION_CODES,
        )
        account = str(request.data.get("handle") or request.data.get("account") or "").strip()
        account = account.lstrip("@").strip()
        if not account or len(account) > 120:
            raise ValidationError({"handle": "TikTok account must be 1-120 characters."})

        blacklist_subquery = InfluencerRestriction.objects.filter(
            tenant=request.user.tenant,
            influencer_id=OuterRef("pk"),
            is_blacklisted=True,
        )
        influencer = (
            Influencer.objects.select_for_update()
            .filter(tenant=request.user.tenant)
            .filter(Q(handle__iexact=account) | Q(code__iexact=account))
            .annotate(is_blacklisted=Exists(blacklist_subquery))
            .order_by("-is_blacklisted", "id")
            .first()
        )
        created = False
        if influencer is None:
            digest = hashlib.sha256(
                f"{request.user.tenant_id}:{account.casefold()}".encode("utf-8")
            ).hexdigest()[:20]
            influencer, created = Influencer.objects.get_or_create(
                tenant=request.user.tenant,
                code=f"tk-{digest}",
                defaults={
                    "name": account,
                    "handle": account,
                    "platform": "TikTok",
                    "status": Influencer.Status.ACTIVE,
                },
            )
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

        is_blacklisted = bool(getattr(influencer, "is_blacklisted", False)) or influencer.restrictions.filter(is_blacklisted=True).exists()
        payload = {
            "id": influencer.id,
            "code": influencer.code,
            "name": influencer.name,
            "handle": influencer.handle,
            "platform": influencer.platform,
            "status": influencer.status,
            "is_blacklisted": is_blacklisted,
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
            ).prefetch_related(
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
        queryset = OutreachTask.objects.filter(
            tenant=request.user.tenant,
        ).select_related("influencer", "store", "owner", "dispatcher", "spu").prefetch_related(
            active_samples
        ).annotate(
            active_linked_count=Count(
                "targets",
                filter=Q(
                    targets__tenant=request.user.tenant,
                    targets__is_deleted=False,
                ),
                distinct=True,
            )
        )
        include_deleted = request.query_params.get("include_deleted", "").lower() in {
            "1", "true", "yes"
        }
        if not include_deleted:
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
        blacklist_subquery = InfluencerRestriction.objects.filter(
            tenant=request.user.tenant,
            influencer_id=OuterRef("pk"),
            is_blacklisted=True,
        )
        influencers = Influencer.objects.filter(
            tenant=request.user.tenant,
            status=Influencer.Status.ACTIVE,
        ).annotate(is_blacklisted=Exists(blacklist_subquery)).order_by("name", "code")[:500]
        stores = stores[:200]
        return success_response({
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
            "influencers": [
                {
                    "id": influencer.id,
                    "code": influencer.code,
                    "name": influencer.name,
                    "handle": influencer.handle,
                    "platform": influencer.platform,
                    "is_blacklisted": influencer.is_blacklisted,
                }
                for influencer in influencers
            ],
        })


class SampleFulfillmentOptionsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        search = request.query_params.get("search", "").strip()
        blacklist_subquery = InfluencerRestriction.objects.filter(
            tenant=request.user.tenant,
            influencer_id=OuterRef("pk"),
            is_blacklisted=True,
        )
        influencers = Influencer.objects.filter(
            tenant=request.user.tenant,
            status=Influencer.Status.ACTIVE,
        ).annotate(is_blacklisted=Exists(blacklist_subquery))
        if search:
            influencers = influencers.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(handle__icontains=search)
            )
        influencers = influencers.order_by("name", "code")[:100]
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
            "influencers": [
                {
                    "id": influencer.id,
                    "code": influencer.code,
                    "name": influencer.name,
                    "handle": influencer.handle,
                    "platform": influencer.platform,
                    "is_blacklisted": influencer.is_blacklisted,
                }
                for influencer in influencers
            ],
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
        ).select_related("influencer")
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
        )
        include_deleted = request.query_params.get("include_deleted", "").lower() in {
            "1", "true", "yes"
        }
        if not include_deleted:
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
                Q(fulfillment_no__icontains=search)
                | Q(outreach_task__task_no__icontains=search)
                | Q(outreach_task__task_name__icontains=search)
                | Q(influencer__name__icontains=search)
                | Q(influencer__handle__icontains=search)
                | Q(store__name__icontains=search)
                | Q(product_name_snapshot__icontains=search)
                | Q(external_product_id__icontains=search)
                | Q(sample_order_no__icontains=search)
            )
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
        return success_response(SampleFulfillmentSerializer(fulfillment).data, status=201 if created else 200)


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
        return success_response(SampleFulfillmentSerializer(fulfillment).data)

    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        fulfillment = self._get(request, pk)
        serializer = SampleFulfillmentUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)
        item_payloads = validated.pop("items", None)
        append_item_payloads = validated.pop("append_items", None)
        items_mode = validated.pop("items_mode", "replace")
        try:
            fulfillment = update_sample_fulfillment(
                user=request.user,
                fulfillment=fulfillment,
                expected_version=_expected_version(request),
                validated_data=validated,
                item_payloads=item_payloads,
                append_item_payloads=append_item_payloads,
                items_mode=items_mode,
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
        fulfillment = get_object_or_404(
            SampleFulfillment, tenant=request.user.tenant, pk=pk, is_deleted=False
        )
        try:
            fulfillment = transition_sample_fulfillment(
                user=request.user,
                fulfillment=fulfillment,
                status=request.data.get("status", ""),
                expected_version=_expected_version(request),
                reason=request.data.get("reason", ""),
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
