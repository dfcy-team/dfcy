import re
import unicodedata

from django.db import migrations, models
from django.db.models.query import QuerySet


TIKTOK_USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{1,255}$")


def _normalize_tiktok_username(value):
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return normalized.strip().lstrip("@").strip().lower()


def normalize_existing_tiktok_identities(apps, schema_editor):
    Influencer = apps.get_model("influencers", "Influencer")
    InfluencerRestriction = apps.get_model("influencers", "InfluencerRestriction")
    SampleFulfillment = apps.get_model("influencers", "SampleFulfillment")
    FulfillmentStatusEvent = apps.get_model("influencers", "FulfillmentStatusEvent")
    Snapshot = apps.get_model("influencers", "BdSampleAttributionSnapshot")

    influencer_ids = list(
        Influencer.objects.filter(platform__iexact="TikTok").values_list(
            "id", flat=True
        )
    )
    for influencer_id in influencer_ids:
        influencer = Influencer.objects.get(pk=influencer_id)
        normalized = _normalize_tiktok_username(influencer.handle)
        canonical = normalized if TIKTOK_USERNAME_PATTERN.fullmatch(normalized) else ""
        if canonical != influencer.handle:
            # Data migrations must bypass runtime identity locks so legacy
            # blacklisted aliases can be canonicalized safely.
            QuerySet(
                model=Influencer,
                using=Influencer.objects.db,
            ).filter(pk=influencer_id).update(handle=canonical)

    snapshot_ids = list(Snapshot.objects.values_list("id", flat=True))
    for snapshot_id in snapshot_ids:
        snapshot = Snapshot.objects.select_related("influencer").get(pk=snapshot_id)
        influencer = snapshot.influencer
        snapshot_handle = _normalize_tiktok_username(snapshot.creator_username)
        canonical = (
            snapshot_handle
            if TIKTOK_USERNAME_PATTERN.fullmatch(snapshot_handle)
            else ""
        )
        if influencer and str(influencer.platform or "").lower() == "tiktok":
            normalized = _normalize_tiktok_username(influencer.handle)
            if TIKTOK_USERNAME_PATTERN.fullmatch(normalized):
                canonical = normalized
        if canonical != snapshot.creator_username:
            QuerySet(
                model=Snapshot,
                using=Snapshot.objects.db,
            ).filter(pk=snapshot_id).update(creator_username=canonical)

    # A TikTok handle is the tenant-scoped business identity. If normalization
    # merges legacy aliases, carry an existing restriction to every alias and
    # close all non-terminal fulfillments consistently.
    identities = {}
    for influencer in Influencer.objects.filter(
        platform__iexact="TikTok",
    ).exclude(handle="").iterator():
        identities.setdefault((influencer.tenant_id, influencer.handle), []).append(
            influencer.id
        )

    terminal_statuses = {"completed", "cancelled", "blacklisted"}
    for (tenant_id, _handle), influencer_ids in identities.items():
        restriction = (
            InfluencerRestriction.objects.filter(
                tenant_id=tenant_id,
                influencer_id__in=influencer_ids,
                is_blacklisted=True,
            )
            .order_by("created_at", "id")
            .first()
        )
        if restriction is None:
            continue

        for influencer_id in influencer_ids:
            existing = InfluencerRestriction.objects.filter(
                tenant_id=tenant_id,
                influencer_id=influencer_id,
            ).first()
            if existing is None:
                InfluencerRestriction.objects.create(
                    tenant_id=tenant_id,
                    influencer_id=influencer_id,
                    is_blacklisted=True,
                    reason=restriction.reason,
                    created_by_id=restriction.created_by_id,
                )
            elif not existing.is_blacklisted:
                existing.is_blacklisted = True
                existing.reason = restriction.reason
                existing.created_by_id = restriction.created_by_id
                existing.save(
                    update_fields=["is_blacklisted", "reason", "created_by"]
                )

        fulfillment_ids = list(
            SampleFulfillment.objects.filter(
                tenant_id=tenant_id,
                influencer_id__in=influencer_ids,
            )
            .exclude(status__in=terminal_statuses)
            .values_list("id", flat=True)
        )
        for fulfillment_id in fulfillment_ids:
            fulfillment = SampleFulfillment.objects.get(pk=fulfillment_id)
            previous_status = fulfillment.status
            finalized_at = fulfillment.finalized_at or restriction.updated_at
            QuerySet(
                model=SampleFulfillment,
                using=SampleFulfillment.objects.db,
            ).filter(pk=fulfillment_id).update(
                status="blacklisted",
                finalized_at=finalized_at,
                version=fulfillment.version + 1,
                updated_at=restriction.updated_at,
            )
            FulfillmentStatusEvent.objects.create(
                tenant_id=tenant_id,
                fulfillment_id=fulfillment.id,
                from_status=previous_status,
                to_status="blacklisted",
                actor_id=restriction.created_by_id,
                reason=restriction.reason or "canonical_handle_blacklisted",
            )


class Migration(migrations.Migration):
    dependencies = [("influencers", "0012_sample_fulfillment_status_baseline")]

    operations = [
        migrations.AlterField(
            model_name="influencer",
            name="handle",
            field=models.CharField(
                blank=True,
                db_comment="TikTok用户名",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="bdsampleattributionsnapshot",
            name="creator_username",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(
            normalize_existing_tiktok_identities,
            migrations.RunPython.noop,
        ),
    ]
