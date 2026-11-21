import re
from urllib.parse import urlsplit

from django.core import signing
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import write_operation_log
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.tenants.models import Tenant

from .models import (
    Influencer, InfluencerPlatformAccount, InfluencerProfile, InfluencerUsernameAlias,
    TikTokCreatorProfileSnapshot, identity_digest, influencer_has_active_restriction,
    influencer_identity_queryset, is_valid_tiktok_username, normalize_tiktok_username,
)
from .platform_accounts import (
    InfluencerFormConflict, _save_validated, assert_account_identity_available, require_influencer_form_access,
)
from .scopes import filter_queryset


_SALT = "influencers.tiktok-username-rename.v1"


def verified_rename_preview(*, actor, influencer, snapshot, creator):
    # The seller API returns the numeric ID inside its official profile URI.
    uri = creator.get("profile_tt_uri")
    if not isinstance(uri, str):
        return None
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if (parts.scheme, parts.netloc, parts.path) != (
        "aweme", "user", f"/profile/{snapshot.external_influencer_id}",
    ):
        return None
    username = normalize_tiktok_username(snapshot.username)
    old = normalize_tiktok_username(influencer.handle)
    if (
        snapshot.identity_status != TikTokCreatorProfileSnapshot.IdentityStatus.HANDLE_MISMATCH
        or not old or not username or len(username) > 255 or not is_valid_tiktok_username(username)
        or not snapshot.nickname or influencer_has_active_restriction(influencer)
    ):
        return None
    return {
        "old_username": old, "username": username, "nickname": snapshot.nickname,
        "profile_url": f"https://www.tiktok.com/@{username}",
        "token": signing.dumps({
            "tenant": actor.tenant_id, "actor": actor.pk, "influencer": influencer.pk,
            "version": influencer.updated_at.isoformat(), "snapshot": snapshot.pk,
            "fetched_at": snapshot.fetched_at.isoformat(), "old_username": old,
            "creator_id": snapshot.external_influencer_id, "username": username,
            "nickname": snapshot.nickname, "store": snapshot.store_id,
        }, salt=_SALT),
    }


@transaction.atomic
def apply_verified_rename(*, user, influencer_id, token):
    from .tiktok_creator_lookup import available_tiktok_lookup_stores

    require_influencer_form_access(user)
    require_all_scope(user, "influencers.manage")
    if not isinstance(token, str) or len(token) > 4096:
        raise ValidationError("请先核验平台用户名。")
    try:
        proof = signing.loads(token, salt=_SALT, max_age=300)
    except signing.BadSignature as exc:
        raise ValidationError("核验凭据无效或已过期，请重新查询。") from exc
    if (proof["tenant"], proof["actor"], proof["influencer"]) != (user.tenant_id, user.pk, influencer_id):
        raise PermissionDenied("核验凭据不属于当前档案或操作人。")
    if not any(store["id"] == proof["store"] for store in available_tiktok_lookup_stores(user)):
        raise PermissionDenied("该店铺已不在当前账号的授权范围内。")

    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    influencer = get_object_or_404(filter_queryset(
        user, Influencer.objects.select_for_update().filter(tenant_id=user.tenant_id, is_deleted=False),
        "influencers.manage",
    ), pk=influencer_id)
    if influencer.updated_at.isoformat() != proof["version"] or normalize_tiktok_username(influencer.handle) != proof["old_username"]:
        raise InfluencerFormConflict("档案已更新，请重新查询后再确认。")
    profile = get_object_or_404(InfluencerProfile.objects.select_for_update(),
                                tenant_id=user.tenant_id, influencer=influencer)
    if (
        influencer.platform.strip().lower() != "tiktok"
        or not re.fullmatch(r"[0-9]{1,20}", proof["creator_id"])
        or profile.external_influencer_id.strip() != proof["creator_id"]
        or not TikTokCreatorProfileSnapshot.objects.filter(
            pk=proof["snapshot"], tenant_id=user.tenant_id, influencer=influencer,
            store_id=proof["store"], fetched_at=proof["fetched_at"],
            external_influencer_id=proof["creator_id"],
        ).exists()
    ):
        raise InfluencerFormConflict("平台身份或核验记录已变化，请重新查询。")
    if influencer_has_active_restriction(influencer, for_update=True):
        raise ValidationError("黑名单档案不可变更平台用户名。")
    if influencer_identity_queryset(influencer).exclude(pk=influencer.pk).exists():
        raise ValidationError("原用户名涉及多个档案，请先人工核对。")
    username = proof["username"]
    identity = {"is_active": True, "handle": username, "external_account_id": proof["creator_id"]}
    assert_account_identity_available(
        tenant_id=user.tenant_id, influencer_id=influencer.pk, platform="tiktok", values=identity,
    )
    account = InfluencerPlatformAccount.objects.select_for_update().filter(
        tenant_id=user.tenant_id, influencer=influencer, platform="tiktok",
    ).first()
    if account and (not account.is_active or account.handle != proof["old_username"]
                    or account.external_account_id != proof["creator_id"]):
        raise ValidationError("主平台账号与档案不一致，请先人工核对。")
    before = {"handle": influencer.handle, "display_name": profile.display_name, "profile_url": profile.profile_url}
    profile_url = f"https://www.tiktok.com/@{username}"
    # Ordinary identity writers can propagate changes to historical snapshots.
    # This verified operation must update only this archive and its primary account.
    QuerySet.update(Influencer.objects.filter(pk=influencer.pk, tenant_id=user.tenant_id),
                    handle=username, canonical_handle_digest=identity_digest(username), updated_at=timezone.now())
    influencer.refresh_from_db()
    profile.display_name = proof["nickname"]
    profile.profile_url = profile_url
    _save_validated(profile, update_fields={"display_name", "profile_url"})
    if account:
        account.influencer = influencer
        account.handle = username
        account.display_name = profile.display_name
        account.profile_url = profile_url
        account.updated_by = user
        _save_validated(account, update_fields={"handle", "display_name", "profile_url", "updated_by", "updated_at"})
    InfluencerUsernameAlias.objects.get_or_create(
        tenant_id=user.tenant_id, influencer=influencer, username=proof["old_username"],
    )
    write_operation_log(
        tenant=user.tenant, user=user, module="influencers", action="verified_tiktok_username_rename",
        object_type="influencer", object_id=influencer.pk, before_data=before,
        after_data={"handle": username, "display_name": profile.display_name, "profile_url": profile_url,
                    "snapshot_id": proof["snapshot"], "store_id": proof["store"]},
    )
    return {"username": username, "nickname": profile.display_name, "profile_url": profile_url}
