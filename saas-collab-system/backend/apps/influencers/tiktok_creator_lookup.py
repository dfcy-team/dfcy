"""Tenant-bound TikTok seller lookup for profiles with an already trusted creator ID."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import write_operation_log
from apps.integrations.models import MarketplaceStoreAuthorization
from apps.integrations.production_settings import get_runtime_platform_config
from apps.integrations.readonly_clients import TikTokReadonlyClient
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.tenants.models import Tenant

from .models import Influencer, InfluencerProfile, TikTokCreatorProfileSnapshot, normalize_tiktok_username


def _snapshot_data(snapshot):
    return {
        "store_id": snapshot.store_id,
        "external_influencer_id": snapshot.external_influencer_id,
        "username": snapshot.username,
        "nickname": snapshot.nickname,
        "follower_count": snapshot.follower_count,
        "selection_region": snapshot.selection_region,
        "identity_status": snapshot.identity_status,
        "fetched_at": snapshot.fetched_at.isoformat(),
    }


def creator_snapshots_for_influencer(*, tenant_id, influencer_id):
    return [
        _snapshot_data(row)
        for row in TikTokCreatorProfileSnapshot.objects.filter(
            tenant_id=tenant_id, influencer_id=influencer_id,
        ).order_by("-fetched_at", "-pk")
    ]


def available_tiktok_lookup_stores(actor):
    if not check_user_permission(actor, "integrations.run_live_readonly"):
        return []
    bindings = get_runtime_platform_config("tiktok").get("auto_refresh_bindings") or []
    stores = []
    for authorization in MarketplaceStoreAuthorization.objects.select_related(
        "store", "integration_config"
    ).filter(tenant_id=actor.tenant_id, platform="tiktok", status="active"):
        identity = {
            "tenant_id": actor.tenant_id, "store_code": authorization.store.code,
            "region": authorization.region, "platform_store_id": authorization.platform_store_id,
        }
        if identity in bindings and integration_values_allowed(
            actor, "integrations.run_live_readonly", platform="tiktok",
            environment=authorization.integration_config.environment,
            regions=[authorization.region], config_id=authorization.integration_config_id,
            store_id=authorization.store_id,
        ):
            stores.append({"id": authorization.store_id, "code": authorization.store.code, "region": authorization.region})
    return stores


def lookup_tiktok_creator(*, actor, influencer_id, store_id):
    influencer = Influencer.objects.filter(tenant_id=actor.tenant_id, pk=influencer_id).first()
    if influencer is None or str(influencer.platform).lower() != "tiktok":
        raise ValidationError("Only an existing TikTok influencer can be queried.")
    profile = InfluencerProfile.objects.filter(tenant_id=actor.tenant_id, influencer=influencer).first()
    creator_id = str(profile.external_influencer_id if profile else "").strip()
    if not creator_id:
        return {"status": "candidate", "reason": "external_id_missing", "message": "请人工确认达人 ID 后再查询；不会按昵称自动绑定。"}
    if not creator_id.isascii() or not creator_id.isdecimal() or not 1 <= len(creator_id) <= 20 or int(creator_id) == 0:
        return {"status": "candidate", "reason": "external_id_untrusted", "message": "现有达人 ID 不是可信数字 ID，请人工核对。"}
    if InfluencerProfile.objects.filter(
        tenant_id=actor.tenant_id, external_influencer_id=creator_id,
    ).exclude(influencer_id=influencer_id).exists():
        return {"status": "candidate", "reason": "external_id_conflict", "message": "该达人 ID 关联了多个档案，请先人工核对。"}

    authorizations = list(MarketplaceStoreAuthorization.objects.select_related(
        "store", "integration_config"
    ).filter(tenant_id=actor.tenant_id, store_id=store_id, platform="tiktok", status="active")[:2])
    if len(authorizations) != 1:
        raise ValidationError("请选择本租户唯一有效的 TikTok Shop 店铺授权。")
    authorization = authorizations[0]
    binding = {
        "tenant_id": actor.tenant_id,
        "store_code": authorization.store.code,
        "region": authorization.region,
        "platform_store_id": authorization.platform_store_id,
    }
    if binding not in (get_runtime_platform_config("tiktok").get("auto_refresh_bindings") or []):
        raise PermissionDenied("该店铺未列入 TikTok 受控试点。")
    if not check_user_permission(actor, "integrations.run_live_readonly") or not integration_values_allowed(
        actor, "integrations.run_live_readonly", platform="tiktok",
        environment=authorization.integration_config.environment,
        regions=[authorization.region], config_id=authorization.integration_config_id,
        store_id=authorization.store_id,
    ):
        raise PermissionDenied("缺少该店铺真实只读查询权限。")
    if authorization.expires_at and authorization.expires_at <= timezone.now():
        raise ValidationError("TikTok Shop 授权已过期，请先完成 SaaS 续期。")

    creator = TikTokReadonlyClient(authorization.integration_config, authorization).fetch_marketplace_creator(creator_id)
    username = str(creator.get("username") or "").strip().lstrip("@")
    nickname = str(creator.get("nickname") or "").strip()
    region = str(creator.get("selection_region") or "").strip().upper()
    followers = creator.get("follower_count")
    if followers is not None and (type(followers) is not int or followers < 0 or followers > 2**63 - 1):
        raise ValidationError("TikTok Creator API returned an invalid follower count.")
    if len(username) > 255 or len(nickname) > 160 or len(region) > 8:
        raise ValidationError("TikTok Creator API returned an oversized identity field.")

    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=actor.tenant_id)
        current = Influencer.objects.select_for_update().get(pk=influencer_id, tenant_id=actor.tenant_id)
        current_profile = InfluencerProfile.objects.select_for_update().filter(
            influencer=current, tenant_id=actor.tenant_id,
        ).first()
        if current_profile is None:
            raise ValidationError("达人档案已在查询期间变化，请重新查询。")
        if current_profile.external_influencer_id.strip() != creator_id:
            raise ValidationError("达人 ID 已在查询期间变化，请重新查询。")
        if InfluencerProfile.objects.filter(
            tenant_id=actor.tenant_id, external_influencer_id=creator_id,
        ).exclude(influencer_id=influencer_id).exists():
            raise ValidationError("达人 ID 已与其他档案冲突，请先人工核对。")
        if not region or not username:
            status = TikTokCreatorProfileSnapshot.IdentityStatus.INCOMPLETE
        elif region != authorization.region.upper():
            status = TikTokCreatorProfileSnapshot.IdentityStatus.REGION_MISMATCH
        elif normalize_tiktok_username(username) != normalize_tiktok_username(current.handle):
            status = TikTokCreatorProfileSnapshot.IdentityStatus.HANDLE_MISMATCH
        else:
            status = TikTokCreatorProfileSnapshot.IdentityStatus.MATCHED
        snapshot, _ = TikTokCreatorProfileSnapshot.objects.update_or_create(
            tenant_id=actor.tenant_id, influencer=current, store=authorization.store,
            defaults={
                "fetched_by": actor, "external_influencer_id": creator_id,
                "username": username, "nickname": nickname, "follower_count": followers,
                "selection_region": region, "identity_status": status, "fetched_at": timezone.now(),
            },
        )
        write_operation_log(
            tenant=actor.tenant, user=actor, module="influencers", action="tiktok_creator_lookup",
            object_type="influencer", object_id=current.pk,
            after_data={"store_id": authorization.store_id, "identity_status": status},
        )
    return {"status": "saved", "snapshot": _snapshot_data(snapshot)}
