from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.accounts.models import CustomUser
from apps.common.responses import paginated_data, success_response
from apps.masterdata.models import StatusChoices, StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p2_scopes import require_all_scope

from .models import Influencer, OutreachTarget, OutreachTask, SampleFulfillment, SkuPriceSnapshot, StoreProductListing
from .serializers import (
    InfluencerSerializer,
    OutreachTargetSerializer,
    OutreachTaskSerializer,
    OutreachTaskUpdateSerializer,
    SampleFulfillmentSerializer,
    SkuPriceSnapshotSerializer,
)
from .services import (
    create_outreach_task,
    create_sample_fulfillment,
    add_outreach_target,
    outreach_task_progress,
    soft_delete_outreach_target,
    soft_delete_outreach_task,
    transition_outreach_task,
    transition_sample_fulfillment,
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


class InfluencerCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        queryset = Influencer.objects.filter(tenant=request.user.tenant)
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        if status:
            queryset = queryset.filter(status=status)
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
        return get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)

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


class OutreachTaskCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.outreach.view"
    write_permission_code = "influencers.outreach.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        queryset = OutreachTask.objects.filter(
            tenant=request.user.tenant, is_deleted=False
        ).select_related("influencer", "store", "owner", "dispatcher", "spu").annotate(
            active_linked_count=Count(
                "targets",
                filter=Q(
                    targets__tenant=request.user.tenant,
                    targets__is_deleted=False,
                ),
                distinct=True,
            )
        )
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
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, OutreachTaskSerializer, page=page, page_size=page_size))

    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        serializer = OutreachTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = create_outreach_task(user=request.user, validated_data=serializer.validated_data)
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
        influencers = Influencer.objects.filter(
            tenant=request.user.tenant,
            status=Influencer.Status.ACTIVE,
        ).order_by("name", "code")[:500]
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
                    "platform": influencer.platform,
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
        task = get_object_or_404(
            OutreachTask,
            tenant=request.user.tenant,
            pk=pk,
            is_deleted=False,
        )
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
        task = soft_delete_outreach_task(user=request.user, task=task)
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
            "outreach_task", "influencer", "store", "owner"
        ).prefetch_related("items")
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


class SampleFulfillmentStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.fulfillment.view"
    write_permission_code = "influencers.fulfillment.manage"

    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        fulfillment = get_object_or_404(SampleFulfillment, tenant=request.user.tenant, pk=pk)
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
