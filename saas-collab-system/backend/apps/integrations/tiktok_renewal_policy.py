"""Exact ownership of imported Shop credentials; never applies to Ads tokens."""


def has_verified_oauth_binding(record):
    """Return true only for the durable Shop OAuth flow's exact bound record.

    Imported live-pilot credentials do not create a binding session, so they
    remain ineligible for the OAuth default and must use an explicit binding.
    Token rotation updates the authorization row in place, retaining this FK.
    """
    from datetime import timedelta

    from .models import IntegrationAuditLog, OAuthStateSession, TikTokShopBindingSession

    if getattr(record, "platform", None) != "tiktok" or getattr(record, "pk", None) is None:
        return False
    bindings = TikTokShopBindingSession.objects.filter(
        status=TikTokShopBindingSession.Status.BOUND,
        authorization_id=record.pk,
        tenant_id=record.tenant_id,
        store_id=record.store_id,
        integration_config_id=record.integration_config_id,
        selected_platform_store_id=record.platform_store_id,
        region__iexact=record.region,
        store__external_store_id=record.platform_store_id,
        store__country_code__iexact=record.region,
        store__platform__platform_type="tiktok",
        oauth_session__platform="tiktok",
        oauth_session__status=OAuthStateSession.Status.CONSUMED,
        oauth_session__tenant_id=record.tenant_id,
        oauth_session__store_id=record.store_id,
        oauth_session__integration_config_id=record.integration_config_id,
        oauth_session__region__iexact=record.region,
    ).select_related("oauth_session").order_by("created_at")
    for binding in bindings:
        # The direct callback also permits an explicitly confirmed credential
        # import. That path writes this audit before exchange; it is not proof
        # of provider-originated OAuth and must not gain default renewal.
        manual_import = IntegrationAuditLog.objects.filter(
            tenant_id=record.tenant_id,
            integration_config_id=record.integration_config_id,
            actor_id=binding.initiated_by_id,
            action="oauth_callback",
            masked_detail__result_code="MANUAL_IMPORT_REQUESTED",
            masked_detail__store_id=str(record.store_id),
            created_at__gte=binding.created_at,
            created_at__lte=binding.created_at + timedelta(minutes=15),
        ).exists()
        if not manual_import:
            return True
    return False


def binding_matches(record, bindings, *, require_config=False):
    identity = {
        "tenant_id": record.tenant_id,
        "store_code": record.store.code,
        "region": record.region,
        "platform_store_id": record.platform_store_id,
    }
    for binding in bindings:
        if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in identity.items()):
            continue
        config_id = binding.get("integration_config_id")
        if require_config and config_id is None:
            continue
        if config_id is not None and config_id != record.integration_config_id:
            continue
        return True
    return False
