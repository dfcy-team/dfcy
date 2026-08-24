from collections import defaultdict
from collections.abc import Mapping

from django.db import transaction
from django.utils import timezone

from apps.tenants.models import Tenant

from .models import Influencer, InfluencerProfile, SampleFulfillment, SampleItem


AUTO_NAMESPACE = "auto_cooperation"
COMPLETED_STATUSES = frozenset(
    {
        SampleFulfillment.Status.PUBLISHED,
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.LIVE_CREATOR,
    }
)


def _as_iso(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return timezone.localtime(value).isoformat()


def _aggregate_bucket():
    return {
        "cooperation_count": 0,
        "completed_fulfillment_count": 0,
        "first_cooperation_at": None,
        "stores": {},
        "products": {},
        "skus": {},
    }


def aggregate_influencer_cooperation(*, tenant, batch_size=500):
    """Rebuild automatic cooperation facts for one tenant without touching manual JSON keys."""
    batch_size = max(100, min(int(batch_size or 500), 5000))
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        aggregates = defaultdict(_aggregate_bucket)
        fulfillment_rows = SampleFulfillment.objects.filter(
            tenant=tenant,
            is_deleted=False,
            influencer__tenant=tenant,
        ).values(
            "influencer_id",
            "store_id",
            "store__code",
            "store__name",
            "external_product_id",
            "product_name_snapshot",
            "sample_sent_at",
            "status",
        ).iterator(chunk_size=batch_size)
        for row in fulfillment_rows:
            bucket = aggregates[row["influencer_id"]]
            bucket["cooperation_count"] += 1
            if row["status"] in COMPLETED_STATUSES:
                bucket["completed_fulfillment_count"] += 1
            sampled_at = row["sample_sent_at"]
            if bucket["first_cooperation_at"] is None or sampled_at < bucket["first_cooperation_at"]:
                bucket["first_cooperation_at"] = sampled_at

            store_key = row["store_id"]
            if store_key is not None:
                bucket["stores"][store_key] = {
                    "id": store_key,
                    "code": row["store__code"] or "",
                    "name": row["store__name"] or "",
                }
            product_id = str(row["external_product_id"] or "").strip()
            product_name = str(row["product_name_snapshot"] or "").strip()
            if product_id or product_name:
                bucket["products"][(product_id, product_name)] = {
                    "external_product_id": product_id,
                    "name": product_name,
                }

        item_rows = SampleItem.objects.filter(
            tenant=tenant,
            fulfillment__tenant=tenant,
            fulfillment__is_deleted=False,
        ).values(
            "fulfillment__influencer_id",
            "fulfillment__external_product_id",
            "requested_sku",
            "matched_sku_code",
            "sku__sku_code",
        ).iterator(chunk_size=batch_size)
        for row in item_rows:
            influencer_id = row["fulfillment__influencer_id"]
            sku = next(
                (
                    str(value).strip()
                    for value in (
                        row["requested_sku"],
                        row["matched_sku_code"],
                        row["sku__sku_code"],
                    )
                    if str(value or "").strip()
                ),
                "",
            )
            if sku:
                aggregates[influencer_id]["skus"][sku] = {
                    "sku": sku,
                    "product_id": str(row["fulfillment__external_product_id"] or "").strip(),
                }

        profile_rows = InfluencerProfile.objects.select_for_update().filter(tenant=tenant)
        profiles = {profile.influencer_id: profile for profile in profile_rows}
        target_ids = set(profiles).union(aggregates)
        influencers = {
            influencer.pk: influencer
            for influencer in Influencer.objects.filter(tenant=tenant, pk__in=target_ids)
        }

        created = updated = unchanged = 0
        for influencer_id in sorted(target_ids):
            influencer = influencers.get(influencer_id)
            if influencer is None:
                continue
            bucket = aggregates[influencer_id]
            auto_cooperation = {
                "cooperation_count": bucket["cooperation_count"],
                "completed_fulfillment_count": bucket["completed_fulfillment_count"],
                "first_cooperation_at": _as_iso(bucket["first_cooperation_at"]),
                "stores": sorted(bucket["stores"].values(), key=lambda item: (item["code"], item["id"])),
                "products": sorted(bucket["products"].values(), key=lambda item: (item["external_product_id"], item["name"])),
                "skus": sorted(bucket["skus"].values(), key=lambda item: (item["sku"], item["product_id"])),
            }
            profile = profiles.get(influencer_id)
            if profile is None:
                profile = InfluencerProfile(
                    tenant=tenant,
                    influencer=influencer,
                    product_cooperation_count=bucket["cooperation_count"],
                    cooperation_count=bucket["cooperation_count"],
                    completed_cooperation_count=bucket["completed_fulfillment_count"],
                    fulfilled_cooperation_count=bucket["completed_fulfillment_count"],
                    first_cooperation_at=bucket["first_cooperation_at"],
                    historical_performance={AUTO_NAMESPACE: auto_cooperation},
                )
                profile.save()
                created += 1
                continue

            existing_history = profile.historical_performance
            if not isinstance(existing_history, Mapping):
                existing_history = {}
            history = dict(existing_history)
            history[AUTO_NAMESPACE] = auto_cooperation
            changes = {
                "product_cooperation_count": bucket["cooperation_count"],
                "cooperation_count": bucket["cooperation_count"],
                "completed_cooperation_count": bucket["completed_fulfillment_count"],
                "fulfilled_cooperation_count": bucket["completed_fulfillment_count"],
                "first_cooperation_at": bucket["first_cooperation_at"],
                "historical_performance": history,
            }
            if all(getattr(profile, field) == value for field, value in changes.items()):
                unchanged += 1
                continue
            for field, value in changes.items():
                setattr(profile, field, value)
            profile.save(update_fields=[*changes, "updated_at"])
            updated += 1

    return {
        "tenant_id": tenant.pk,
        "profiles_created": created,
        "profiles_updated": updated,
        "profiles_unchanged": unchanged,
        "cooperation_count": sum(bucket["cooperation_count"] for bucket in aggregates.values()),
    }
