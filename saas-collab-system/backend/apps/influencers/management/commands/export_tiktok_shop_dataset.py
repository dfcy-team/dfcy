"""Export approved Shop data without renewing credentials or writing business rows."""

import json
from collections import Counter

from billiard.exceptions import SoftTimeLimitExceeded

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.integrations.models import MarketplaceStoreAuthorization, marketplace_authorization_api_type
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.influencers.models import InfluencerProfile
from apps.influencers.tiktok_shop_dataset import DatasetError, export_artifact, validate_window


def resolve_export_scope(actor, store_ids, creator_limit):
    if not actor.is_active or not check_user_permission(actor, "integrations.run_live_readonly"):
        raise DatasetError("live_readonly_permission_required")
    if not 1 <= len(store_ids) <= 2 or len(set(store_ids)) != len(store_ids) or not 0 <= creator_limit <= 20:
        raise DatasetError("invalid_trial_scope")
    if creator_limit:
        if not check_user_permission(actor, "influencers.manage"):
            raise DatasetError("influencer_profile_read_permission_required")
        require_all_scope(actor, "influencers.manage")
    auths = list(MarketplaceStoreAuthorization.objects.select_related("store", "integration_config").filter(
        tenant_id=actor.tenant_id, store_id__in=store_ids, platform="tiktok", status="active"))
    if Counter(auth.store_id for auth in auths) != Counter(store_ids):
        raise DatasetError("unique_active_shop_authorization_required")
    for auth in auths:
        config = auth.integration_config
        if (config.tenant_id != actor.tenant_id or auth.store.tenant_id != actor.tenant_id
                or config.platform != "tiktok" or marketplace_authorization_api_type(config) != "marketplace"
                or not integration_values_allowed(actor, "integrations.run_live_readonly", platform="tiktok",
                    environment=config.environment, regions=[auth.region], config_id=config.pk, store_id=auth.store_id)):
            raise DatasetError("store_scope_not_authorized")
    # A trusted ID must be unique in the tenant, not merely within this subset.
    duplicated = InfluencerProfile.objects.filter(tenant_id=actor.tenant_id).values("external_influencer_id").annotate(
        n=Count("pk")).filter(n__gt=1).values_list("external_influencer_id", flat=True)
    profiles = InfluencerProfile.objects.filter(tenant_id=actor.tenant_id, is_active=True,
        influencer__platform__iexact="tiktok").exclude(external_influencer_id="").exclude(
        external_influencer_id__in=duplicated).order_by("influencer_id").values_list("external_influencer_id", "influencer_id")
    seeds = []
    for external_id, influencer_id in profiles.iterator():
        if len(seeds) >= creator_limit:
            break
        if external_id.isascii() and external_id.isdecimal() and 1 <= len(external_id) <= 20 and int(external_id) > 0:
            seeds.append((external_id, influencer_id))
    return sorted(auths, key=lambda auth: auth.store_id), seeds


class Command(BaseCommand):
    help = "Export one or two authorized TikTok shops to a new restricted artifact directory; no business writes."

    def add_arguments(self, parser):
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--store-ids", type=int, nargs="+", required=True)
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--creator-limit", type=int, default=5)
        parser.add_argument("--staging", action="store_true", help="Export schema2 evidence, without canonical writes.")
        parser.add_argument("--resume", action="store_true", help="Reuse verified staging pages in the same scoped directory.")
        parser.add_argument("--enrich-orders", action="store_true", help="Staging only: optional ordinary order payment evidence.")

    def handle(self, *args, **options):
        try:
            if (options["resume"] or options["enrich_orders"]) and not options["staging"]:
                raise DatasetError("staging_required")
            validate_window(options["start_date"], options["end_date"])
            actor = get_user_model().objects.get(pk=options["actor_id"])
            auths, seeds = resolve_export_scope(actor, options["store_ids"], options["creator_limit"])
            manifest, digest = export_artifact(output_dir=options["output_dir"], actor=actor, authorizations=auths,
                start_date=options["start_date"], end_date=options["end_date"], creator_seeds=seeds,
                staging=options["staging"], resume=options["resume"], enrich_orders=options["enrich_orders"])
        except (TimeoutError, SoftTimeLimitExceeded):
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, DatasetError) else "export_failed_no_data_assumed"
            raise CommandError(code) from None
        self.stdout.write(json.dumps({"manifest_sha256": digest, "tenant_id": actor.tenant_id,
            "components": [{key: component[key] for key in ("kind", "store_id", "status", "row_count", "request_count", "reason")
                            if key in component} for component in manifest["components"]]}))
