"""Run the approved two-shop TikTok Auction Campaign spend pilot once."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.integrations.models import PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, TikTokAdsSyncLease
from apps.integrations.tiktok_ads_pilot import sync_seven_complete_days
from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant


ACCOUNT_COUNTS = {"TK1PH": 2, "TKKJ1PH": 10}


class Command(BaseCommand):
    help = "Dry-run or synchronously run the 12-account, seven-complete-day Ads pilot."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--recover-stale", action="store_true")

    def handle(self, *args, **options):
        if options["tenant_id"] != 1 or options["actor"] != "yxj":
            raise CommandError("Ads pilot requires tenant 1 and actor yxj.")
        if options["recover_stale"] and not options["apply"]:
            raise CommandError("Stale recovery requires --recover-stale --apply.")
        if not Tenant.objects.filter(pk=1, code="tenant-1", status=Tenant.Status.ACTIVE).exists():
            raise CommandError("Approved pilot tenant is unavailable.")
        if not get_user_model().objects.filter(
            username="yxj", tenant_id=1, is_active=True, is_staff=True,
            is_superuser=True, user_type="internal",
        ).exists():
            raise CommandError("Approved yxj administrator is unavailable.")
        stores = {store.code: store for store in StoreMaster.objects.filter(tenant_id=1, code__in=ACCOUNT_COUNTS)}
        if set(stores) != set(ACCOUNT_COUNTS) or any(
            store.platform.platform_type != "tiktok" for store in stores.values()
        ):
            raise CommandError("Approved TikTok pilot stores are unavailable.")
        mappings = list(TikTokAdsAdvertiserMapping.objects.select_related("store", "integration_config").filter(tenant_id=1))
        recovering = options["recover_stale"]
        if len(mappings) != 12 or (not recovering and any(mapping.enabled for mapping in mappings)):
            raise CommandError("Exactly 12 Ads mappings in the expected state are required.")
        counts = {code: 0 for code in ACCOUNT_COUNTS}
        configs = {}
        for mapping in mappings:
            code = mapping.store.code
            if code not in counts or mapping.store_id != stores[code].pk:
                raise CommandError("Ads mapping is outside the approved stores.")
            config = mapping.integration_config
            if (config.tenant_id != 1 or config.account_alias != f"live-ads-pilot-{code.lower()}"
                    or config.environment != "pilot" or config.status != config.Status.VERIFIED
                    or not config.network_enabled or (not recovering and config.sync_read_enabled)
                    or config.sync_write_enabled):
                raise CommandError("Ads config is not in the expected pilot state.")
            mapping.full_clean()
            configs[code] = config
            counts[code] += 1
        if counts != ACCOUNT_COUNTS or len({config.pk for config in configs.values()}) != 2:
            raise CommandError("Ads mappings do not match the approved 2+10 scope.")
        config_ids = [config.pk for config in configs.values()]
        mapping_ids = [mapping.pk for mapping in mappings]
        if recovering:
            if not any(mapping.enabled or mapping.integration_config.sync_read_enabled for mapping in mappings):
                raise CommandError("Ads pilot is already disabled; stale recovery is unnecessary.")
            with transaction.atomic():
                lease = TikTokAdsSyncLease.objects.select_for_update().filter(tenant_id=1).first()
                now = timezone.now()
                if lease and lease.owner_token and lease.lease_expires_at > now:
                    raise CommandError("An active Ads sync lease exists; refusing stale recovery.")
                locked = list(TikTokAdsAdvertiserMapping.objects.select_for_update().filter(
                    tenant_id=1, pk__in=mapping_ids,
                ))
                if len(locked) != 12:
                    raise CommandError("Ads mappings changed before stale recovery.")
                locked_configs = list(PlatformIntegrationConfig.objects.select_for_update().filter(
                    tenant_id=1, pk__in=config_ids,
                ))
                if len(locked_configs) != 2 or not (
                    any(mapping.enabled for mapping in locked)
                    or any(config.sync_read_enabled for config in locked_configs)
                ):
                    raise CommandError("Ads config switches changed before stale recovery.")
                if lease:
                    lease.owner_token = ""
                    lease.generation += 1
                    lease.lease_expires_at = now
                    lease.save(update_fields=["owner_token", "generation", "lease_expires_at", "updated_at"])
                TikTokAdsAdvertiserMapping.objects.filter(tenant_id=1, pk__in=mapping_ids).update(enabled=False)
                PlatformIntegrationConfig.objects.filter(tenant_id=1, pk__in=config_ids).update(sync_read_enabled=False)
            self.stdout.write("RECOVERED: stale Ads pilot switches disabled; no API call or report write.")
            return
        if not options["apply"]:
            self.stdout.write("DRY RUN: 12 Ads mappings verified; no network or database writes.")
            return
        with transaction.atomic():
            locked = list(TikTokAdsAdvertiserMapping.objects.select_for_update().filter(
                tenant_id=1, pk__in=mapping_ids,
            ))
            if len(locked) != 12 or any(mapping.enabled for mapping in locked):
                raise CommandError("Ads mappings changed before pilot execution.")
            changed = PlatformIntegrationConfig.objects.filter(
                tenant_id=1, pk__in=config_ids, sync_read_enabled=False,
                sync_write_enabled=False, status=PlatformIntegrationConfig.Status.VERIFIED,
            ).update(sync_read_enabled=True)
            if changed != 2:
                raise CommandError("Ads configs changed before pilot execution.")
            changed = TikTokAdsAdvertiserMapping.objects.filter(
                tenant_id=1, pk__in=mapping_ids, enabled=False,
            ).update(enabled=True)
            if changed != 12:
                raise CommandError("Ads mappings changed before pilot execution.")
        lease_state = {}

        def note_lease(owner, generation):
            lease_state.update(owner=owner, generation=generation)

        try:
            results = sync_seven_complete_days(
                tenant_id=1, approved_store_ids=[stores["TK1PH"].pk, stores["TKKJ1PH"].pk],
                on_lease_claim=note_lease,
            )
        finally:
            with transaction.atomic():
                lease = TikTokAdsSyncLease.objects.select_for_update().filter(tenant_id=1).first()
                if lease_state:
                    may_close = bool(
                        lease and lease.generation == lease_state["generation"]
                        and lease.owner_token in {"", lease_state["owner"]}
                    )
                else:
                    may_close = not lease or not lease.owner_token or lease.lease_expires_at <= timezone.now()
                if may_close:
                    TikTokAdsAdvertiserMapping.objects.filter(tenant_id=1, pk__in=mapping_ids).update(enabled=False)
                    PlatformIntegrationConfig.objects.filter(tenant_id=1, pk__in=config_ids).update(sync_read_enabled=False)
        written = sum(row["days_written"] for row in results)
        missing = sum(len(row["missing_days"]) for row in results)
        self.stdout.write(
            f"SUCCESS: Auction Campaign spend, accounts={len(results)}, days_written={written}, "
            f"missing_account_days={missing}; read-only switches disabled."
        )
