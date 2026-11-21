import pytest
from django.utils import timezone

from apps.audit.models import OperationLog
from apps.influencers.models import (
    Influencer, InfluencerPlatformAccount, InfluencerProfile, InfluencerUsernameAlias,
    SampleFulfillment, TikTokCreatorProfileSnapshot, identity_digest,
)
from apps.influencers.username_rename import verified_rename_preview
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import store_for, user_with_permissions

pytestmark = pytest.mark.django_db


@pytest.fixture
def records(monkeypatch):
    tenant = Tenant.objects.create(code="verified-rename", name="Verified rename")
    user, client = user_with_permissions(tenant, "rename", "influencers.view", "influencers.manage")
    store = store_for(tenant, "rename")
    influencer = Influencer.objects.create(tenant=tenant, code="original", name="Legacy name",
                                           platform="TikTok", handle="old.name")
    profile = InfluencerProfile.objects.create(tenant=tenant, influencer=influencer,
                                               external_influencer_id="123456789", display_name="Old name")
    account = InfluencerPlatformAccount.objects.create(
        tenant=tenant, influencer=influencer, platform="tiktok", handle="old.name",
        external_account_id="123456789", created_by=user, updated_by=user,
    )
    snapshot = TikTokCreatorProfileSnapshot.objects.create(
        tenant=tenant, influencer=influencer, store=store, fetched_by=user, external_influencer_id="123456789",
        username="new.name", nickname="New name", selection_region="PH",
        identity_status="handle_mismatch", fetched_at=timezone.now(),
    )
    monkeypatch.setattr("apps.influencers.tiktok_creator_lookup.available_tiktok_lookup_stores",
                        lambda actor: [{"id": store.pk}])
    return user, client, store, influencer, profile, account, snapshot


def preview(records, uri="aweme://user/profile/123456789?sec_uid=value"):
    user, _, _, influencer, _, _, snapshot = records
    return verified_rename_preview(actor=user, influencer=influencer, snapshot=snapshot,
                                   creator={"profile_tt_uri": uri})


def apply(client, influencer, token):
    return client.post(f"/api/internal/influencers/{influencer.pk}/tiktok-creator/",
                       {"rename_token": token}, format="json")


def test_verified_rename_preserves_archive_and_sample_and_searches_old_username(records):
    user, client, store, influencer, profile, account, _ = records
    sample = SampleFulfillment.objects.create(
        tenant=user.tenant, fulfillment_no="RENAME-1", request_key="rename-key", request_hash="hash",
        influencer=influencer, store=store, owner=user, sample_order_no="original-order",
    )
    token = preview(records)["token"]
    response = apply(client, influencer, token)
    assert response.status_code == 200, response.data
    for row in (influencer, profile, account, sample):
        row.refresh_from_db()
    assert (influencer.handle, influencer.canonical_handle_digest, influencer.code) == (
        "new.name", identity_digest("new.name"), "original",
    )
    assert profile.display_name == account.display_name == "New name"
    assert profile.profile_url == account.profile_url == "https://www.tiktok.com/@new.name"
    assert profile.external_influencer_id == account.external_account_id == "123456789"
    assert account.handle == "new.name"
    assert sample.influencer_id == influencer.pk and sample.sample_order_no == "original-order"
    assert InfluencerUsernameAlias.objects.get(influencer=influencer).username == "old.name"
    assert OperationLog.objects.filter(action="verified_tiktok_username_rename", object_id=str(influencer.pk)).count() == 1
    assert apply(client, influencer, token).status_code == 409
    result = client.get("/api/internal/influencers/", {"include_nickname_id": "true", "search": "@old.name"})
    assert result.status_code == 200, result.data
    assert [row["id"] for row in result.data["data"]["results"]] == [influencer.pk]


@pytest.mark.parametrize("uri", ["", "aweme://user/profile/987654321", "https://evil.example/profile/123456789"])
def test_unverifiable_id_cannot_issue_token(records, uri):
    assert preview(records, uri) is None


def test_taken_username_and_tampered_token_are_rejected(records):
    user, client, _, influencer, _, _, _ = records
    token = preview(records)["token"]
    assert apply(client, influencer, token + "x").status_code == 400
    Influencer.objects.create(tenant=user.tenant, code="other", name="Other", platform="TikTok", handle="new.name")
    assert apply(client, influencer, token).status_code == 400
    influencer.refresh_from_db()
    assert influencer.handle == "old.name"
    assert not InfluencerUsernameAlias.objects.exists()


def test_another_actor_cannot_use_preview(records):
    user, _, _, influencer, _, _, _ = records
    _, another = user_with_permissions(user.tenant, "other-renamer", "influencers.view", "influencers.manage")
    assert apply(another, influencer, preview(records)["token"]).status_code == 403


def test_soft_deleted_influencer_cannot_be_renamed_with_preissued_proof(records):
    user, client, _, influencer, profile, account, _ = records
    token = preview(records)["token"]
    influencer.status = Influencer.Status.INACTIVE
    influencer.is_deleted = True
    influencer.deleted_at = timezone.now()
    influencer.save(update_fields=["status", "is_deleted", "deleted_at"])

    response = apply(client, influencer, token)
    assert response.status_code == 404
    influencer.refresh_from_db()
    profile.refresh_from_db()
    account.refresh_from_db()
    assert influencer.handle == "old.name" and influencer.is_deleted
    assert account.handle == "old.name"
    assert profile.display_name == "Old name"
    assert not InfluencerUsernameAlias.objects.exists()
    assert not OperationLog.objects.filter(action="verified_tiktok_username_rename").exists()
