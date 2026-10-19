"""Read-only inspection of non-formal dataset observations."""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.integrations.ads_subject import mapping_allowed
from apps.integrations.models import TikTokAdsAdvertiserMapping
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.permissions.ui_p6_scopes import analytics_dimensions_allowed
from .models import TikTokDatasetStageBatch, TikTokDatasetStagePartition


def _visible_batches(user, batches):
    """Hide the entire batch if any GMV partition fails the read intersection."""
    partitions = list(TikTokDatasetStagePartition.objects.filter(batch__in=batches, kind="gmv_max").values(
        "batch_id", "tenant_id", "batch__store_id", "evidence"))
    if not partitions:
        return batches
    if not all(check_user_permission(user, code) for code in ("integrations.store.view", "analytics.view")):
        return batches.exclude(pk__in={p["batch_id"] for p in partitions})
    mapping_ids = {p["evidence"]["mapping_id"] for p in partitions
                   if isinstance(p["evidence"], dict) and type(p["evidence"].get("mapping_id")) is int
                   and 0 < p["evidence"]["mapping_id"] <= 2**63 - 1}
    mappings = TikTokAdsAdvertiserMapping.objects.filter(
        pk__in=mapping_ids, tenant_id=user.tenant_id, store__tenant_id=user.tenant_id,
        store__platform__tenant_id=user.tenant_id, store__platform__platform_type="tiktok",
        integration_config__tenant_id=user.tenant_id, integration_config__platform="tiktok",
    ).select_related("store__platform", "integration_config")
    visible = {}
    for mapping in mappings:
        try:
            allowed = mapping_allowed(user, mapping, "integrations.store.view") and analytics_dimensions_allowed(
                user, "analytics.view", {"platform": "tiktok", "store_id": str(mapping.store_id),
                                          "country": mapping.store.country_code})
        except PermissionDenied:
            allowed = False
        if allowed:
            visible[mapping.pk] = mapping
    hidden = set()
    for partition in partitions:
        evidence = partition["evidence"]
        mapping_id = evidence.get("mapping_id") if isinstance(evidence, dict) else None
        mapping = visible.get(mapping_id) if type(mapping_id) is int else None
        if (mapping is None or partition["tenant_id"] != user.tenant_id
                or mapping.store_id != partition["batch__store_id"]
                or any(evidence.get(field) != getattr(mapping, field) for field in ("advertiser_id", "currency", "timezone"))):
            hidden.add(partition["batch_id"])
    return batches.exclude(pk__in=hidden)


class TikTokDatasetQualityView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"

    def get(self, request, batch_id=None):
        require_all_scope(request.user, self.read_permission_code)
        batches = _visible_batches(request.user, TikTokDatasetStageBatch.objects.filter(tenant_id=request.user.tenant_id))
        if batch_id is None:
            # Historical PARTIAL evidence remains visible even after a newer export.
            totals = TikTokDatasetStagePartition.objects.filter(tenant_id=request.user.tenant_id, batch__in=batches).aggregate(
                partial=Count("pk", filter=Q(quality="partial")),
                failed=Count("pk", filter=Q(quality="failed")),
                pending=Count("pk", filter=Q(import_status="pending")),
                rejected=Count("pk", filter=Q(rejected_count__gt=0)),
            )
            return success_response({"is_formal": False, "batch_count": batches.count(), **totals,
                "missing_count": None, "missing_count_basis": "source_total_semantics_unverified",
                "results": list(batches.order_by("-pk").values("id", "store_id", "window_start", "window_end")[:20])})
        batch = get_object_or_404(batches, pk=batch_id)
        try:
            offset = int(request.query_params.get("offset", 0))
            if not 0 <= offset <= 10000:
                raise ValueError
        except ValueError:
            raise ValidationError("Invalid bounded offset.") from None
        partitions = batch.partitions.filter(tenant_id=request.user.tenant_id).order_by("kind", "partition_date")
        requested_partition = request.query_params.get("partition_id")
        records = []
        if requested_partition is not None:
            try:
                partition_id = int(requested_partition)
            except ValueError:
                raise ValidationError("Invalid partition.") from None
            partition = get_object_or_404(partitions, pk=partition_id)
            if partition.kind in {"affiliate_orders", "videos"}:
                # Match the registered two-action policy of the formal BD report.
                for code in ("influencers.outreach.view", "influencers.fulfillment.view"):
                    if not check_user_permission(request.user, code):
                        raise PermissionDenied("Monetary observations require both BD report view permissions.")
                    require_all_scope(request.user, code)
            records = list(partition.records.filter(tenant_id=request.user.tenant_id).order_by("pk").values("record_type", "payload")[offset:offset + 50])
        return success_response({"id": batch.pk, "is_formal": False, "store_id": batch.store_id,
            "manifest_sha256": batch.manifest_digest, "source_created_at": batch.source_created_at,
            "window_start": batch.window_start, "window_end": batch.window_end,
            "partitions": list(partitions.values("id", "kind", "partition_date", "quality", "reason",
                "observed_count", "expected_count", "next_offset", "imported_count", "rejected_count", "import_status")),
            "records": records, "offset": offset, "page_size": 50})
