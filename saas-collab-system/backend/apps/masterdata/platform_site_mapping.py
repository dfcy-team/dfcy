from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.audit.models import OperationLog
from apps.audit.services import write_operation_log

from .models import PlatformSiteMaster, StatusChoices, StoreMaster


ACTION = "platform_site_mapping_apply"
OBJECT_TYPE = "platform_site_mapping_batch"


def _site_index(tenant):
    result = defaultdict(list)
    for site in PlatformSiteMaster.objects.filter(tenant=tenant, status=StatusChoices.ACTIVE).select_related("platform"):
        result[(site.platform_id, str(site.country_code or "").strip().upper())].append(site)
    return result


def mapping_preview(tenant, store_ids=None, *, lock=False):
    queryset = StoreMaster.objects.filter(tenant=tenant, platform_site__isnull=True).select_related("platform")
    if store_ids is not None:
        queryset = queryset.filter(pk__in=store_ids)
    if lock:
        queryset = queryset.select_for_update()
    index = _site_index(tenant)
    rows = []
    for store in queryset.order_by("id"):
        candidates = index.get((store.platform_id, str(store.country_code or "").strip().upper()), [])
        status = "exact" if len(candidates) == 1 else "ambiguous" if len(candidates) > 1 else "unmatched"
        matched = candidates[0] if len(candidates) == 1 else None
        rows.append({
            "store_id": store.id,
            "store_code": store.code,
            "store_name": store.name,
            "platform_id": store.platform_id,
            "platform_code": store.platform.code,
            "platform_name": store.platform.name,
            "country_code": str(store.country_code or "").strip().upper(),
            "status": status,
            "confidence": "high" if status == "exact" else "none",
            "candidate_site_ids": [item.id for item in candidates],
            "candidates": [
                {
                    "id": item.id,
                    "site_code": item.site_code,
                    "name": item.name,
                    "country_code": item.country_code,
                }
                for item in candidates
            ],
            "before": {"platform_site_id": None},
            "after": {"platform_site_id": matched.id, "platform_site_name": matched.name} if matched else None,
            "reason": "unique platform and country match" if matched else "multiple matching sites" if candidates else "no matching active site",
        })
    return {
        "total": len(rows),
        "exact": sum(row["status"] == "exact" for row in rows),
        "ambiguous": sum(row["status"] == "ambiguous" for row in rows),
        "unmatched": sum(row["status"] == "unmatched" for row in rows),
        "rows": rows,
    }


def apply_exact_mappings(*, tenant, user, store_ids, idempotency_key):
    with transaction.atomic():
        tenant.__class__.objects.select_for_update().get(pk=tenant.pk)
        previous = OperationLog.objects.filter(
            tenant=tenant, module="masterdata", action=ACTION, object_type=OBJECT_TYPE, object_id=idempotency_key,
        ).first()
        if previous:
            return {**previous.after_data, "idempotent": True}
        preview = mapping_preview(tenant, store_ids, lock=True)
        rows_by_id = {row["store_id"]: row for row in preview["rows"]}
        applied = []
        conflicts = []
        skipped = []
        for store_id in store_ids:
            row = rows_by_id.get(store_id)
            if row is None:
                skipped.append({"store_id": store_id, "reason": "store missing or already linked"})
            elif row["status"] != "exact":
                conflicts.append(row)
            else:
                StoreMaster.objects.filter(pk=store_id, tenant=tenant, platform_site__isnull=True).update(
                    platform_site_id=row["after"]["platform_site_id"],
                    updated_at=timezone.now(),
                )
                applied.append(row)
        result = {
            "requested": len(store_ids), "applied": len(applied), "skipped": len(skipped),
            "conflicts": len(conflicts), "applied_rows": applied, "skipped_rows": skipped,
            "conflict_rows": conflicts, "idempotent": False,
        }
        write_operation_log(
            tenant=tenant, user=user, module="masterdata", action=ACTION,
            object_type=OBJECT_TYPE, object_id=idempotency_key,
            before_data={"store_ids": store_ids}, after_data=result,
        )
        return result
