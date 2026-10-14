from importlib import import_module
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, migrations, models
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.core.management import call_command
from io import StringIO
import json
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers import platform_accounts as aggregate
from apps.influencers.models import (
    Influencer, InfluencerContact, InfluencerPlatformAccount, InfluencerProfile, InfluencerRestriction,
    identity_digest,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _role(user, code, permissions, scope=DataScope.ScopeType.ALL):
    role = Role.objects.create(tenant=user.tenant, code=code, name=code)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    for code in permissions:
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code, "module": "influencers", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope, config={"all": True} if scope == "all" else {})
    return role


def _records(code="accounts", *, permissions=("influencers.manage", "influencers.view"), scope=DataScope.ScopeType.ALL, handle="primary.creator", external_id=""):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"{code}-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    _role(user, "accounts", permissions, scope)
    influencer = Influencer.objects.create(tenant=tenant, code=f"{code}-creator", name="Creator", platform="tiktok", handle=handle)
    profile = InfluencerProfile.objects.create(tenant=tenant, influencer=influencer, display_name="Creator", external_influencer_id=external_id)
    client = APIClient()
    client.force_authenticate(user)
    return SimpleNamespace(tenant=tenant, user=user, influencer=influencer, profile=profile, client=client)


def _save(record, payload, version=None):
    return aggregate.save_influencer_aggregate(
        user=record.user, influencer_id=record.influencer.pk, payload=payload,
        expected_updated_at=version or record.influencer.updated_at,
    )


def _account(record, platform="facebook", handle="secondary.creator", **kwargs):
    return InfluencerPlatformAccount.objects.create(
        tenant=record.tenant, influencer=record.influencer, platform=platform, handle=handle,
        created_by=kwargs.pop("created_by", record.user), updated_by=kwargs.pop("updated_by", record.user), **kwargs,
    )


def _form_url(record):
    return f"/api/internal/influencers/{record.influencer.pk}/?include_form=true"


def test_0028_is_schema_only_and_ordinary_mysql_compatible_constraints():
    migration = import_module("apps.influencers.migrations.0028_influencer_platform_account").Migration
    assert ("influencers", "0026_sampleitem_warehouse") in migration.dependencies
    assert len(migration.operations) == 1
    assert isinstance(migration.operations[0], migrations.CreateModel)
    unique = [constraint for constraint in migration.operations[0].options["constraints"] if isinstance(constraint, models.UniqueConstraint)]
    assert len(unique) == 3
    assert all(constraint.condition is None for constraint in unique)
    assert unique[0].fields == ("tenant", "influencer", "platform")


@pytest.mark.parametrize("field,value", [("handle", "reserved.creator"), ("profile", {"external_influencer_id": "ReservedID"})])
def test_legacy_create_and_patch_cannot_claim_another_parents_child(field, value):
    record = _records()
    _account(record, handle="reserved.creator", external_account_id="ReservedID")
    payload = {"code": "new-legacy", "name": "New legacy", "platform": "facebook", field: value}
    response = record.client.post("/api/internal/influencers/", payload, format="json")
    assert response.status_code == 400
    assert not Influencer.objects.filter(code="new-legacy").exists()
    other = Influencer.objects.create(tenant=record.tenant, code="other-primary", name="Other", platform="facebook", handle="other.creator")
    profile = InfluencerProfile.objects.create(tenant=record.tenant, influencer=other)
    version = other.updated_at
    response = record.client.patch(f"/api/internal/influencers/{other.pk}/", {field: value}, format="json")
    assert response.status_code == 400
    other.refresh_from_db()
    profile.refresh_from_db()
    assert other.handle == "other.creator" and other.updated_at == version
    assert profile.external_influencer_id == ""


def test_profileless_create_can_reopen_complete_form():
    record = _records()
    response = record.client.post("/api/internal/influencers/?include_form=true", {
        "code": "no-profile", "name": "No profile", "platform": "facebook", "handle": "new.manual",
    }, format="json")
    assert response.status_code == 201
    pk = response.data["data"]["id"]
    response = record.client.get(f"/api/internal/influencers/{pk}/?include_form=true")
    assert response.status_code == 200
    assert response.data["data"]["profile"] is None
    assert response.data["data"]["contacts"] == []
    assert len(response.data["data"]["platform_accounts"]) == 1


@pytest.mark.parametrize("provided", [None, "", "   "])
def test_aggregate_create_allocates_code_without_user_input(provided):
    record = _records()
    payload = {"platform": "facebook", "nickname_id": "new.manual", "account_nickname": "New nickname"}
    if provided is not None:
        payload["code"] = provided
    response = record.client.post("/api/internal/influencers/?include_form=true", payload, format="json")
    assert response.status_code == 201, response.data
    created = Influencer.objects.get(pk=response.data["data"]["id"])
    assert created.code.startswith("DRDA-") and len(created.code) == 37
    assert response.data["data"]["code"] == created.code
    assert created.handle == "new.manual" and created.name == "New nickname"
    record.influencer.refresh_from_db()
    assert record.influencer.code == "accounts-creator"


def test_generated_code_collision_retries_without_rewriting_existing_archive(monkeypatch):
    record = _records()
    existing = Influencer.objects.create(tenant=record.tenant, code="DRDA-" + "a" * 32, name="Existing", platform="facebook")
    tokens = iter([SimpleNamespace(hex="a" * 32), SimpleNamespace(hex="b" * 32)])
    monkeypatch.setattr(aggregate, "uuid4", lambda: next(tokens))
    created = aggregate.save_influencer_aggregate(user=record.user, payload={"platform": "facebook", "account_nickname": "New nickname"})
    assert created.code == "DRDA-" + "b" * 32
    existing.refresh_from_db()
    assert existing.code == "DRDA-" + "a" * 32 and existing.name == "Existing"


def test_generated_code_collision_exhaustion_is_bounded_and_rolls_back(monkeypatch):
    record = _records()
    Influencer.objects.create(tenant=record.tenant, code="DRDA-" + "a" * 32, name="Existing", platform="facebook")
    before = Influencer.objects.count()
    calls = []
    def collision():
        calls.append(True)
        return SimpleNamespace(hex="a" * 32)
    monkeypatch.setattr(aggregate, "uuid4", collision)
    with pytest.raises(ValidationError, match="allocate"):
        aggregate.save_influencer_aggregate(user=record.user, payload={"platform": "facebook", "account_nickname": "New nickname"})
    assert len(calls) == 5 and Influencer.objects.count() == before


@pytest.mark.parametrize("value", ["123", "这是主页备注", "facebook.com/example", "javascript:alert(1)", "<script>alert(1)</script>", ""])
def test_profile_reference_accepts_plain_text_on_create_and_edit(value):
    record = _records()
    response = record.client.post("/api/internal/influencers/?include_form=true", {
        "platform": "facebook", "nickname_id": "new.manual",
        "profile": {"profile_url": value, "profile_notes": "Synthetic reference test"},
    }, format="json")
    assert response.status_code == 201, response.data
    form = response.data["data"]
    assert form["code"].startswith("DRDA-") and form["profile"]["profile_url"] == value
    created = Influencer.objects.get(pk=form["id"])
    assert created.profile.profile_url == value
    changed = record.client.patch(f"/api/internal/influencers/{created.pk}/?include_form=true", {
        "profile": {"profile_url": "任意新内容"},
    }, format="json", HTTP_IF_MATCH=form["updated_at"])
    assert changed.status_code == 200, changed.data
    created.profile.refresh_from_db()
    assert created.profile.profile_url == "任意新内容"


def test_profile_reference_migration_only_changes_validation_state():
    migration = import_module("apps.influencers.migrations.0032_profile_reference_plain_text").Migration
    assert migration.dependencies == [("influencers", "0031_influence_archive_associations")]
    assert len(migration.operations) == 1
    operation = migration.operations[0]
    assert isinstance(operation, migrations.SeparateDatabaseAndState)
    assert operation.database_operations == [] and len(operation.state_operations) == 1
    field = operation.state_operations[0].field
    assert type(field) is models.CharField and field.max_length == 500 and field.blank
    assert type(InfluencerProfile._meta.get_field("profile_url")) is models.CharField


def test_identity_index_writers_and_tiktok_duplicate_fanout():
    record = _records(handle="Before.Creator", external_id=" CaseSensitiveID ")
    sibling = Influencer.objects.create(tenant=record.tenant, code="duplicate-primary", name="Duplicate", platform="TikTok", handle="before.creator")
    record.influencer.handle = "after.creator"
    record.influencer.save(update_fields=["handle"])
    sibling.refresh_from_db()
    record.profile.refresh_from_db()
    assert record.influencer.canonical_handle_digest == identity_digest("after.creator")
    assert sibling.canonical_handle_digest == identity_digest("after.creator")
    assert record.profile.canonical_external_id_digest == identity_digest("CaseSensitiveID")
    record.profile.external_influencer_id = "NextID"
    record.profile.save(update_fields=["external_influencer_id"])
    record.profile.refresh_from_db()
    assert record.profile.canonical_external_id_digest == identity_digest("NextID")


def test_bounded_identity_backfill_only_changes_derived_fields_and_is_idempotent():
    record = _records()
    version = record.influencer.updated_at
    profile_version = record.profile.updated_at
    QuerySet.update(Influencer.objects.filter(pk=record.influencer.pk), canonical_handle_digest=None)
    QuerySet.update(InfluencerProfile.objects.filter(pk=record.profile.pk), canonical_external_id_digest=None)
    with pytest.raises(ValidationError, match="not ready"):
        _save(record, {"platform_accounts": [{"platform": "facebook", "handle": "new.facebook"}]})
    stream = StringIO()
    call_command("backfill_influencer_identity_indexes", tenant=record.tenant.pk, limit=1, stdout=stream)
    assert json.loads(stream.getvalue())["remaining_parents"] == 1
    stream = StringIO()
    call_command("backfill_influencer_identity_indexes", tenant=record.tenant.pk, limit=1, apply=True, stdout=stream)
    assert json.loads(stream.getvalue())["remaining_parents"] == 0
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    assert record.influencer.updated_at == version and record.profile.updated_at == profile_version
    assert record.influencer.handle == "primary.creator" and record.profile.external_influencer_id == ""
    stream = StringIO()
    call_command("backfill_influencer_identity_indexes", tenant=record.tenant.pk, limit=1, apply=True, stdout=stream)
    assert json.loads(stream.getvalue())["parents"] == 0
    assert json.loads(stream.getvalue())["profiles"] == 0


def test_metadata_only_account_changes_skip_legacy_identity_queries():
    record = _records()
    _account(record)
    QuerySet.update(Influencer.objects.filter(pk=record.influencer.pk), canonical_handle_digest=None)
    with CaptureQueriesContext(connection) as captured:
        _save(record, {"platform_accounts": [{"platform": "facebook", "display_name": "Updated metadata"}]})
    assert not any("canonical_handle_digest" in query["sql"] and "IS NULL" in query["sql"] for query in captured)


def test_virtual_primary_is_read_only_fallback_and_contacts_are_active_only():
    record = _records(external_id="CreatorID")
    contact = InfluencerContact.objects.create(tenant=record.tenant, influencer=record.influencer, channel="facebook", value="not-an-account", created_by=record.user)
    record.profile.platforms = ["youtube", "instagram"]
    record.profile.save()
    response = record.client.get(_form_url(record))
    assert response.status_code == 200
    form = response.data["data"]
    assert form["updated_at"] and form["handle"] == "primary.creator"
    assert form["registered_platforms"] == ["tiktok"]
    assert len(form["contacts"]) == 1
    primary = form["platform_accounts"][0]
    assert primary["id"] is None and primary["source"] == "legacy" and primary["is_primary"]
    assert primary["external_account_id"] == "CreatorID" and primary["follower_count"] is None
    saved = record.client.patch(_form_url(record), {"platform": "TikTok", "platform_accounts": [primary]}, format="json", HTTP_IF_MATCH=form["updated_at"])
    assert saved.status_code == 200
    assert saved.data["data"]["updated_at"] == form["updated_at"]
    assert not InfluencerPlatformAccount.objects.exists()
    contact.is_active = False
    contact.save()
    assert record.client.get(_form_url(record)).data["data"]["contacts"] == []


def test_default_reads_and_legacy_write_responses_do_not_expose_account_identifiers():
    record = _records()
    _account(record)
    for url in ("/api/internal/influencers/", f"/api/internal/influencers/{record.influencer.pk}/"):
        response = record.client.get(url)
        assert response.status_code == 200
        row = response.data["data"]["results"][0] if url.endswith("influencers/") else response.data["data"]
        assert "handle" not in row and "nickname_id" not in row and "platform_accounts" not in row
        assert row["registered_platforms"] == ["facebook", "tiktok"]
    response = record.client.patch(f"/api/internal/influencers/{record.influencer.pk}/", {"name": "Renamed"}, format="json", HTTP_IF_MATCH=record.influencer.updated_at.isoformat())
    assert response.status_code == 200
    assert "handle" not in response.data["data"] and "platform_accounts" not in response.data["data"]


def test_nickname_purpose_returns_username_not_decorated_name_and_searches_it():
    record = _records(handle="misschedly", external_id="6971589531640529922", permissions=("influencers.view",))
    record.profile.display_name = "Miss CHE DIY"
    record.profile.save()
    url = "/api/internal/influencers/?include_nickname_id=true&search=misschedly"
    response = record.client.get(url)
    assert response.status_code == 200
    row = response.data["data"]["results"][0]
    assert row["nickname_id"] == "misschedly" and row["account_nickname"] == "Miss CHE DIY"
    assert row["profile"]["external_influencer_id"] == "6971589531640529922"
    assert "handle" not in row and "platform_accounts" not in row
    response = record.client.get(f"/api/internal/influencers/{record.influencer.pk}/?include_nickname_id=true")
    assert response.data["data"]["nickname_id"] == "misschedly"
    assert record.client.get("/api/internal/influencers/?include_nickname_id=false").data["data"]["results"][0].get("nickname_id") is None


@pytest.mark.parametrize("actor", ["external", "rpa", "own", "no_view"])
def test_nickname_read_purpose_does_not_bypass_actor_or_scope(actor):
    record = _records(permissions=("influencers.manage",) if actor == "no_view" else ("influencers.view",), scope=DataScope.ScopeType.OWN if actor == "own" else DataScope.ScopeType.ALL)
    if actor in {"external", "rpa"}:
        record.user.user_type = actor
    for url in ("/api/internal/influencers/?include_nickname_id=true", f"/api/internal/influencers/{record.influencer.pk}/?include_nickname_id=true"):
        assert record.client.get(url).status_code == 403


def test_nickname_purpose_is_tenant_isolated_and_empty_identity_is_not_inferred():
    record = _records(handle="")
    other = _records("foreign-nickname", handle="misschedly")
    record.profile.profile_url = "https://www.tiktok.com/@candidate.creator"
    record.profile.save()
    response = record.client.get("/api/internal/influencers/?include_nickname_id=true")
    assert response.data["data"]["count"] == 1
    assert response.data["data"]["results"][0]["nickname_id"] == ""
    assert record.client.get(f"/api/internal/influencers/{other.influencer.pk}/?include_nickname_id=true").status_code == 404
    record.influencer.refresh_from_db()
    assert record.influencer.handle == ""


def test_alias_create_and_update_preserve_legacy_name_numeric_id_and_cas():
    record = _records()
    response = record.client.post("/api/internal/influencers/", {
        "code": "alias-new", "platform": "tiktok", "nickname_id": " @Misschedly ",
        "account_nickname": "Miss CHE DIY", "profile": {"external_influencer_id": "6971589531640529922"},
        "platform_accounts": [{"platform": "facebook", "nickname_id": "fb.creator", "account_nickname": "FB nickname"}],
    }, format="json")
    assert response.status_code == 201, response.data
    form = response.data["data"]
    assert form["nickname_id"] == "misschedly" and form["account_nickname"] == "Miss CHE DIY"
    parent = Influencer.objects.get(pk=form["id"])
    assert parent.name == "Miss CHE DIY"
    response = record.client.patch(f"/api/internal/influencers/{parent.pk}/", {
        "nickname_id": "misschedly", "account_nickname": "Changed nickname",
    }, format="json", HTTP_IF_MATCH=form["updated_at"])
    assert response.status_code == 200, response.data
    parent.refresh_from_db()
    assert parent.name == "Miss CHE DIY" and parent.handle == "misschedly"
    assert parent.profile.display_name == "Changed nickname"
    assert parent.profile.external_influencer_id == "6971589531640529922"
    assert response.data["data"]["account_nickname"] == "Changed nickname"
    stale = record.client.patch(f"/api/internal/influencers/{parent.pk}/", {"account_nickname": "Stale"}, format="json", HTTP_IF_MATCH=form["updated_at"])
    assert stale.status_code == 409


@pytest.mark.parametrize("legacy_name", ["misschedly", "Miss CHE DIY"])
def test_empty_account_nickname_never_falls_back_to_legacy_name(legacy_name):
    record = _records(handle="misschedly", external_id="6971589531640529922")
    record.influencer.name = legacy_name
    record.influencer.save(update_fields=["name"])
    record.profile.display_name = ""
    record.profile.save(update_fields=["display_name"])
    for purpose in ("include_nickname_id=true", "include_form=true"):
        response = record.client.get(f"/api/internal/influencers/{record.influencer.pk}/?{purpose}")
        assert response.status_code == 200
        data = response.data["data"]
        assert data["nickname_id"] == "misschedly" and data["account_nickname"] == ""
        assert data["name"] == legacy_name
        if purpose == "include_form=true":
            assert data["platform_accounts"][0]["account_nickname"] == ""
            assert data["profile"]["external_influencer_id"] == "6971589531640529922"
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    assert record.influencer.name == legacy_name and record.profile.display_name == ""


def test_same_stored_nickname_is_preserved_and_clearing_does_not_restore_it():
    record = _records(handle="misschedly", external_id="6971589531640529922")
    record.influencer.name = "misschedly"
    record.influencer.save(update_fields=["name"])
    record.profile.display_name = "misschedly"
    record.profile.save(update_fields=["display_name"])
    _account(record, platform="tiktok", handle="misschedly", external_account_id="6971589531640529922", display_name="misschedly")
    original_code = record.influencer.code
    response = record.client.get(_form_url(record))
    assert response.data["data"]["account_nickname"] == "misschedly"
    version = response.data["data"]["updated_at"]
    response = record.client.patch(_form_url(record), {"account_nickname": ""}, format="json", HTTP_IF_MATCH=version)
    assert response.status_code == 200, response.data
    assert response.data["data"]["account_nickname"] == ""
    assert response.data["data"]["platform_accounts"][0]["account_nickname"] == ""
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    assert record.influencer.name == record.influencer.handle == "misschedly"
    assert record.influencer.code == original_code
    assert record.profile.display_name == "" and record.profile.external_influencer_id == "6971589531640529922"
    assert record.client.get(_form_url(record)).data["data"]["account_nickname"] == ""


@pytest.mark.parametrize("payload", [
    {"nickname_id": "different", "handle": "primary.creator"},
    {"account_nickname": "One", "profile": {"display_name": "Two"}},
    {"platform_accounts": [{"platform": "facebook", "nickname_id": "one", "handle": "two"}]},
    {"platform_accounts": [{"platform": "facebook", "account_nickname": "One", "display_name": "Two"}]},
    {"nickname_id": None}, {"account_nickname": {"unexpected": True}},
    {"nickname_id": "new.creator"},
])
def test_conflicting_invalid_or_changed_primary_aliases_roll_back(payload):
    record = _records(external_id="NumericID")
    before = record.influencer.updated_at
    with pytest.raises(ValidationError):
        _save(record, payload)
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    assert record.influencer.handle == "primary.creator" and record.influencer.updated_at == before
    assert record.profile.display_name == "Creator" and record.profile.external_influencer_id == "NumericID"
    assert not InfluencerPlatformAccount.objects.exists()


def test_matching_normalized_aliases_omissions_and_primary_nickname_sync():
    record = _records()
    _account(record, platform="tiktok", handle="primary.creator", display_name="Creator")
    saved = _save(record, {"nickname_id": " @PRIMARY.Creator ", "handle": "primary.creator", "account_nickname": " Updated ", "profile": {"display_name": "Updated"}})
    assert saved.name == "Creator" and saved.profile.display_name == "Updated"
    assert saved.platform_accounts.get(platform="tiktok").display_name == "Updated"
    record.influencer = saved
    saved = _save(record, {"category": "Unrelated"})
    assert saved.handle == "primary.creator" and saved.profile.display_name == "Updated"


@pytest.mark.parametrize("length", [121, 160])
def test_full_account_nickname_is_preserved_with_bounded_legacy_create_name(length):
    record = _records()
    nickname = "N" * length
    response = record.client.post("/api/internal/influencers/", {
        "code": "long-nickname", "platform": "tiktok", "nickname_id": "new.creator", "account_nickname": nickname,
    }, format="json")
    assert response.status_code == 201, response.data
    parent = Influencer.objects.get(pk=response.data["data"]["id"])
    assert len(parent.name) == 120 and parent.profile.display_name == nickname
    assert response.data["data"]["account_nickname"] == nickname


def test_legacy_profile_nickname_patch_syncs_primary_child_and_keeps_response_redacted():
    record = _records(external_id="NumericID")
    _account(record, platform="tiktok", handle="primary.creator", external_account_id="NumericID", display_name="Creator")
    response = record.client.patch(f"/api/internal/influencers/{record.influencer.pk}/", {
        "profile": {"display_name": "Legacy updated"},
    }, format="json", HTTP_IF_MATCH=record.influencer.updated_at.isoformat())
    assert response.status_code == 200, response.data
    assert "nickname_id" not in response.data["data"] and "handle" not in response.data["data"]
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    child = record.influencer.platform_accounts.get(platform="tiktok")
    assert record.profile.display_name == child.display_name == "Legacy updated"
    assert record.influencer.name == "Creator" and record.influencer.handle == child.handle == "primary.creator"
    assert record.profile.external_influencer_id == child.external_account_id == "NumericID"


def test_legacy_profile_nickname_patch_rolls_back_child_and_profile_on_audit_failure(monkeypatch):
    record = _records()
    _account(record, platform="tiktok", handle="primary.creator", display_name="Creator")
    def fail(**kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(aggregate, "write_operation_log", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        record.client.patch(f"/api/internal/influencers/{record.influencer.pk}/", {"profile": {"display_name": "Rolled back"}}, format="json", HTTP_IF_MATCH=record.influencer.updated_at.isoformat())
    record.profile.refresh_from_db()
    assert record.profile.display_name == "Creator"
    assert record.influencer.platform_accounts.get(platform="tiktok").display_name == "Creator"


@pytest.mark.parametrize("payload", [None, [{}], ["nickname_id"], "nickname_id", 42])
def test_nonobject_request_bodies_return_400_without_writes(payload):
    record = _records()
    before = record.influencer.updated_at
    audit_count = OperationLog.objects.count()
    for method, url in (("POST", "/api/internal/influencers/"), ("PATCH", f"/api/internal/influencers/{record.influencer.pk}/")):
        response = record.client.generic(method, url, data=json.dumps(payload), content_type="application/json", HTTP_IF_MATCH=before.isoformat())
        assert response.status_code == 400, response.data
    record.influencer.refresh_from_db()
    assert record.influencer.updated_at == before
    assert Influencer.objects.filter(tenant=record.tenant).count() == 1
    assert not InfluencerPlatformAccount.objects.filter(tenant=record.tenant).exists()
    assert OperationLog.objects.count() == audit_count


def test_form_read_manage_only_permission_is_sufficient():
    record = _records(permissions=("influencers.manage",))
    assert record.client.get(_form_url(record)).status_code == 200


@pytest.mark.parametrize("scope", [DataScope.ScopeType.ALL, DataScope.ScopeType.OWN])
def test_form_read_and_service_require_manage_action_and_its_all_scope(scope):
    record = _records(permissions=("influencers.view",), scope=scope)
    assert record.client.get(_form_url(record)).status_code == 403
    with pytest.raises(PermissionDenied):
        aggregate.get_influencer_form(user=record.user, influencer_id=record.influencer.pk)
    with pytest.raises(PermissionDenied):
        _save(record, {"platform_accounts": []})
    _role(record.user, "manage-own", ("influencers.manage",), DataScope.ScopeType.OWN)
    assert record.client.get(_form_url(record)).status_code == 403
    with pytest.raises(PermissionDenied):
        _save(record, {"platform_accounts": []})


@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_form_service_rejects_noninternal_actor_even_with_roles(user_type):
    record = _records()
    record.user.user_type = user_type
    with pytest.raises(PermissionDenied):
        _save(record, {"platform_accounts": []})


def test_foreign_parent_and_account_ids_are_not_accepted():
    record = _records()
    other = _records("other")
    foreign = _account(other)
    assert record.client.get(_form_url(other)).status_code == 404
    response = record.client.patch(_form_url(other), {"platform_accounts": []}, format="json", HTTP_IF_MATCH=other.influencer.updated_at.isoformat())
    assert response.status_code == 404
    with pytest.raises(ValidationError):
        _save(record, {"platform_accounts": [{"id": foreign.pk, "platform": "facebook", "handle": "mine"}]})
    assert InfluencerPlatformAccount.objects.filter(tenant=record.tenant).count() == 0


def test_model_protects_tenant_actors_parent_and_bulk_writes():
    record = _records()
    other = _records("other")
    with pytest.raises(DjangoValidationError):
        _account(record, updated_by=other.user)
    row = _account(record)
    row.influencer = other.influencer
    row.tenant = other.tenant
    row.created_by = other.user
    row.updated_by = other.user
    with pytest.raises(DjangoValidationError):
        row.save()
    with pytest.raises(DjangoValidationError):
        InfluencerPlatformAccount.objects.filter(pk=row.pk).update(is_active=False)
    with pytest.raises(DjangoValidationError):
        InfluencerPlatformAccount.objects.bulk_create([])
    with pytest.raises(ProtectedError):
        record.influencer.delete()


def test_atomic_create_returns_saved_aggregate_and_allows_manual_nickname_without_primary_handle():
    record = _records()
    response = record.client.post("/api/internal/influencers/?include_form=true", {
        "code": "manual-nickname", "name": "Manual nickname", "platform": "tiktok",
        "profile": {"display_name": "Manual nickname"},
        "contacts": [{"channel": "email", "value": "creator@example.test"}],
        "platform_accounts": [{"platform": "instagram", "handle": " @Secondary.Creator ", "follower_count": 0}],
    }, format="json")
    assert response.status_code == 201, response.data
    form = response.data["data"]
    assert form["id"] and form["updated_at"] and form["handle"] == ""
    assert len(form["contacts"]) == 1
    assert form["registered_platforms"] == ["instagram", "tiktok"]
    child = InfluencerPlatformAccount.objects.get(influencer_id=form["id"])
    assert child.handle == "secondary.creator" and child.follower_count == 0
    assert child.created_by_id == record.user.pk and child.updated_by_id == record.user.pk
    assert form["platform_accounts"][0]["id"] is None
    empty = record.client.post("/api/internal/influencers/?include_form=true", {"code": "blank-primary", "name": "Nickname", "platform": "tiktok", "profile": {}, "contacts": [], "platform_accounts": []}, format="json")
    assert empty.status_code == 201 and not InfluencerPlatformAccount.objects.filter(influencer_id=empty.data["data"]["id"]).exists()


def test_invalid_create_rolls_back_parent_profile_contacts_and_audit():
    record = _records()
    before = OperationLog.objects.count()
    response = record.client.post("/api/internal/influencers/?include_form=true", {
        "code": "invalid-create", "name": "Invalid", "platform": "tiktok",
        "profile": {"display_name": "Invalid"}, "contacts": [{"channel": "email", "value": "x@example.test"}],
        "platform_accounts": [{"platform": "instagram", "handle": ""}],
    }, format="json")
    assert response.status_code == 400
    assert not Influencer.objects.filter(code="invalid-create").exists()
    assert InfluencerContact.objects.count() == 0 and InfluencerPlatformAccount.objects.count() == 0
    assert OperationLog.objects.count() == before


@pytest.mark.parametrize("section", ["profile", "contacts", "platform_accounts"])
def test_null_sections_are_rejected_and_do_not_mutate(section):
    record = _records()
    with pytest.raises(ValidationError):
        _save(record, {section: None, "name": "Should roll back"})
    record.influencer.refresh_from_db()
    assert record.influencer.name == "Creator"


def test_omitted_sections_profile_partial_and_empty_arrays_have_distinct_semantics():
    record = _records(external_id="OriginalID")
    child = _account(record)
    contact = InfluencerContact.objects.create(tenant=record.tenant, influencer=record.influencer, channel="email", value="creator@example.test", created_by=record.user, is_primary=True)
    first = _save(record, {"profile": {"level": "new"}})
    assert first.profile.external_influencer_id == "OriginalID" and first.profile.display_name == "Creator"
    contact.refresh_from_db()
    assert contact.is_active
    original_version = first.updated_at
    second = _save(record, {"platform_accounts": []}, version=original_version)
    assert second.updated_at == original_version
    third = _save(record, {"contacts": []}, version=original_version)
    assert third.updated_at > original_version
    child.refresh_from_db()
    contact.refresh_from_db()
    assert child.is_active and not contact.is_active and not contact.is_primary


def test_timestamp_cas_is_required_and_checked_after_parent_lock():
    record = _records()
    assert record.client.patch(_form_url(record), {"platform_accounts": []}, format="json").status_code == 400
    first = _save(record, {"name": "First save"})
    response = record.client.patch(_form_url(record), {"name": "Lost save", "platform_accounts": []}, format="json", HTTP_IF_MATCH=record.influencer.updated_at.isoformat())
    assert response.status_code == 409
    record.influencer.refresh_from_db()
    assert record.influencer.name == "First save" and record.influencer.updated_at == first.updated_at


@pytest.mark.parametrize("version", [
    "", "   ", "not-a-timestamp", "2026-02-30T12:00:00Z",
    "2026-13-01T12:00:00Z", "2026-01-32T12:00:00Z",
    "2026-01-01T25:00:00Z", "2026-01-01T12:00:00+25:00",
    "2026-01-01T12:00:00", '"2026-02-30T12:00:00Z"',
])
def test_invalid_if_match_returns_field_error_without_aggregate_mutations(version):
    record = _records()
    child = _account(record, follower_count=5)
    contact = InfluencerContact.objects.create(
        tenant=record.tenant, influencer=record.influencer, channel="email",
        value="original@example.test", is_primary=True, created_by=record.user,
    )
    before_version = record.influencer.updated_at
    before_logs = OperationLog.objects.count()
    response = record.client.patch(_form_url(record), {
        "name": "Rejected name", "profile": {"level": "Rejected level"},
        "contacts": [{"channel": "email", "value": "replacement@example.test"}],
        "platform_accounts": [{"platform": "facebook", "follower_count": 99}],
    }, format="json", HTTP_IF_MATCH=version)
    assert response.status_code == 400, response.data
    assert response.data["success"] is False
    assert "If-Match" in response.data["data"]
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    child.refresh_from_db()
    contact.refresh_from_db()
    assert record.influencer.name == "Creator" and record.influencer.updated_at == before_version
    assert record.profile.level == "" and child.follower_count == 5
    assert contact.is_active and contact.is_primary and InfluencerContact.objects.count() == 1
    assert OperationLog.objects.count() == before_logs


@pytest.mark.parametrize("kind", ["missing", "wrong_type", "naive_datetime"])
def test_aggregate_service_rejects_invalid_version_types(kind):
    record = _records()
    version = {"missing": None, "wrong_type": 123, "naive_datetime": record.influencer.updated_at.replace(tzinfo=None)}[kind]
    with pytest.raises(ValidationError) as error:
        aggregate.save_influencer_aggregate(
            user=record.user, influencer_id=record.influencer.pk,
            payload={"name": "Rejected"}, expected_updated_at=version,
        )
    assert "If-Match" in error.value.detail
    record.influencer.refresh_from_db()
    assert record.influencer.name == "Creator"
    assert not OperationLog.objects.exists()


@pytest.mark.parametrize("kind", ["utc", "quoted", "offset"])
def test_valid_if_match_timestamp_formats_keep_cas_compatibility(kind):
    record = _records()
    version = record.influencer.updated_at.isoformat()
    if kind == "utc":
        version = version.replace("+00:00", "Z")
    elif kind == "quoted":
        version = f'"{version}"'
    else:
        version = record.influencer.updated_at.astimezone(timezone.get_fixed_timezone(480)).isoformat()
    response = record.client.patch(_form_url(record), {"name": "Accepted"}, format="json", HTTP_IF_MATCH=version)
    assert response.status_code == 200, response.data
    record.influencer.refresh_from_db()
    assert record.influencer.name == "Accepted"
    assert OperationLog.objects.filter(object_id=record.influencer.pk, action="aggregate_update").count() == 1


def test_tenant_parent_child_lock_order_and_strict_single_parent_version_advance(monkeypatch):
    record = _records()
    previous = record.influencer.updated_at
    locks = []
    original = QuerySet.select_for_update

    def observe(queryset, *args, **kwargs):
        locks.append(queryset.model)
        return original(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", observe)
    monkeypatch.setattr(aggregate.timezone, "now", lambda: previous - timedelta(seconds=1))
    saved = _save(record, {"name": "Changed", "profile": {"level": "changed"}, "contacts": [{"channel": "email", "value": "creator@example.test"}], "platform_accounts": [{"platform": "facebook", "handle": "secondary"}]})
    assert locks[:2] == [Tenant, Influencer]
    assert locks.index(Influencer) < locks.index(InfluencerProfile) < locks.index(InfluencerContact) < locks.index(InfluencerPlatformAccount)
    assert saved.updated_at == previous + timedelta(microseconds=1)


def test_audit_failure_rolls_back_all_sections_and_version(monkeypatch):
    record = _records()
    contact = InfluencerContact.objects.create(tenant=record.tenant, influencer=record.influencer, channel="email", value="old@example.test", is_primary=True, created_by=record.user)
    before = record.influencer.updated_at

    def fail(**kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(aggregate, "write_operation_log", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        _save(record, {"name": "Rolled back", "profile": {"level": "new"}, "contacts": [{"channel": "email", "value": "new@example.test", "is_primary": True}], "platform_accounts": [{"platform": "facebook", "handle": "secondary"}]})
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    contact.refresh_from_db()
    assert record.influencer.name == "Creator" and record.influencer.updated_at == before
    assert record.profile.level == "" and contact.is_active and contact.is_primary
    assert InfluencerContact.objects.count() == 1 and not InfluencerPlatformAccount.objects.exists()


@pytest.mark.parametrize("payload", [
    {"platform": "instagram"}, {"handle": "different"},
    {"platform_accounts": [{"platform": "tiktok", "is_active": False}]},
    {"platform_accounts": [{"platform": "tiktok", "handle": "different"}]},
    {"platform_accounts": [{"platform": "facebook", "handle": "secondary", "is_primary": True}]},
    {"profile": {"external_influencer_id": "ChangedID"}},
    {"platform_accounts": [{"platform": "tiktok", "external_account_id": "ChangedID"}]},
])
def test_aggregate_primary_identity_cannot_change_or_promote(payload):
    record = _records(external_id="ExistingID")
    with pytest.raises(ValidationError):
        _save(record, payload)


def test_blank_primary_external_id_can_fill_once_and_audit_is_identifier_safe():
    record = _records()
    saved = _save(record, {"profile": {"external_influencer_id": "CaseSensitiveID"}, "platform_accounts": []})
    assert saved.profile.external_influencer_id == "CaseSensitiveID"
    assert not InfluencerPlatformAccount.objects.exists()
    log = OperationLog.objects.get(object_id=record.influencer.pk, action="aggregate_update")
    assert log.after_data["primary_external_id_filled"] is True
    assert log.after_data["external_id_digest"] == aggregate._digest("CaseSensitiveID")
    assert "CaseSensitiveID" not in str(log.after_data) and "primary.creator" not in str(log.after_data)
    with pytest.raises(ValidationError):
        _save(record, {"profile": {"external_influencer_id": "Replacement"}}, version=saved.updated_at)


def test_persisted_primary_external_id_fill_keeps_legacy_and_child_in_sync():
    record = _records()
    child = _account(record, "tiktok", record.influencer.handle)
    _save(record, {"profile": {"external_influencer_id": "FilledOnce"}, "platform_accounts": []})
    child.refresh_from_db()
    record.profile.refresh_from_db()
    assert child.external_account_id == record.profile.external_influencer_id == "FilledOnce"


def test_secondary_edits_never_change_parent_legacy_identity_or_lookup_profile():
    record = _records(external_id="TikTokID")
    before = (record.influencer.pk, record.influencer.platform, record.influencer.handle, record.influencer.follower_count)
    _save(record, {"platform_accounts": [{"platform": "facebook", "handle": " @Facebook.Creator ", "external_account_id": "FacebookID", "follower_count": 400}]})
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    assert before == (record.influencer.pk, record.influencer.platform, record.influencer.handle, record.influencer.follower_count)
    assert record.profile.external_influencer_id == "TikTokID" and record.profile.platforms == []


def test_blacklisted_parent_accepts_unchanged_echo_but_rejects_account_changes():
    record = _records()
    child = _account(record)
    InfluencerRestriction.objects.create(tenant=record.tenant, influencer=record.influencer, is_blacklisted=True, reason="test restriction", created_by=record.user)
    form = record.client.get(_form_url(record)).data["data"]
    response = record.client.patch(_form_url(record), {"platform": "TikTok", "platform_accounts": form["platform_accounts"]}, format="json", HTTP_IF_MATCH=form["updated_at"])
    assert response.status_code == 200
    assert response.data["data"]["updated_at"] == form["updated_at"]
    with pytest.raises(ValidationError):
        _save(record, {"platform_accounts": [{"platform": "facebook", "is_active": False}]})
    child.refresh_from_db()
    assert child.is_active


def test_normalized_identity_duplicates_and_legacy_reservations_do_not_merge():
    record = _records()
    second = Influencer.objects.create(tenant=record.tenant, code="second", name="Second", platform="instagram", handle=" @Legacy.Handle ")
    with pytest.raises(ValidationError):
        _save(record, {"platform_accounts": [{"platform": "instagram", "handle": "legacy.handle"}]})
    _account(record, external_account_id="ExternalID")
    other = SimpleNamespace(user=record.user, tenant=record.tenant, influencer=second)
    for fields in ({"handle": " @SECONDARY.CREATOR "}, {"handle": "unique", "external_account_id": "ExternalID"}):
        with pytest.raises(ValidationError):
            _save(other, {"platform_accounts": [{"platform": "facebook", **fields}]})
    assert Influencer.objects.filter(tenant=record.tenant).count() == 2
    assert InfluencerPlatformAccount.objects.count() == 1


def test_legacy_external_id_collision_and_cross_tenant_same_identity():
    record = _records()
    parent = Influencer.objects.create(tenant=record.tenant, code="legacy-facebook", name="Legacy", platform="Facebook", handle="legacy")
    InfluencerProfile.objects.create(tenant=record.tenant, influencer=parent, external_influencer_id="ExternalID")
    with pytest.raises(ValidationError):
        _save(record, {"platform_accounts": [{"platform": "facebook", "handle": "unique", "external_account_id": "ExternalID"}]})
    _account(record)
    other = _records("other")
    saved = _save(other, {"platform_accounts": [{"platform": "facebook", "handle": "secondary.creator"}]})
    assert len(saved._platform_account_rows) == 1


def test_inactive_slot_releases_digests_reactivation_checks_identity_and_slot_is_reused():
    record = _records()
    row = _account(record)
    saved = _save(record, {"platform_accounts": [{"platform": "facebook", "is_active": False}]})
    row.refresh_from_db()
    assert row.active_handle_digest is None and row.active_external_id_digest is None
    second = Influencer.objects.create(tenant=record.tenant, code="second", name="Second", platform="tiktok", handle="second")
    claimant = SimpleNamespace(tenant=record.tenant, user=record.user, influencer=second)
    _account(claimant)
    with pytest.raises(ValidationError):
        _save(record, {"platform_accounts": [{"platform": "facebook", "is_active": True}]}, version=saved.updated_at)
    updated = _save(record, {"platform_accounts": [{"platform": "facebook", "handle": "replacement", "is_active": True}]}, version=saved.updated_at)
    assert updated._platform_account_rows[0].pk == row.pk
    assert updated._platform_account_rows[0].active_handle_digest == aggregate._digest("replacement")
    assert InfluencerPlatformAccount.objects.filter(influencer=record.influencer).count() == 1


def test_external_ids_preserve_case_and_nfkc_handles_use_active_digests():
    record = _records()
    row = _account(record, handle=" \uff20\uff33\uff45\uff43\uff4f\uff4e\uff44\uff41\uff52\uff59 ", external_account_id=" MixedCase ")
    assert row.handle == "secondary" and row.external_account_id == "MixedCase"
    assert row.active_handle_digest == aggregate._digest("secondary")
    assert row.active_external_id_digest == aggregate._digest("MixedCase")
    second = Influencer.objects.create(tenant=record.tenant, code="second", name="Second", platform="tiktok", handle="second")
    other = SimpleNamespace(tenant=record.tenant, user=record.user, influencer=second)
    _save(other, {"platform_accounts": [{"platform": "facebook", "handle": "different", "external_account_id": "mixedcase"}]})


@pytest.mark.parametrize("accounts", [
    [{"platform": "facebook", "handle": "x"}, {"platform": "Facebook", "handle": "y"}],
    [{"platform": "unknown", "handle": "x"}],
    [{"platform": "facebook", "handle": "x"}] * 5,
    [{"platform": "facebook", "handle": "x", "follower_count": -1}],
    [{"platform": "facebook", "handle": "x" * 256}],
])
def test_invalid_account_payload_is_rejected(accounts):
    record = _records()
    with pytest.raises(ValidationError):
        _save(record, {"platform_accounts": accounts})
    assert not InfluencerPlatformAccount.objects.exists()


def test_list_filters_active_children_or_legacy_and_queries_remain_page_bounded():
    record = _records()
    for index in range(12):
        parent = Influencer.objects.create(tenant=record.tenant, code=f"page-{index}", name=f"Page {index}", platform="tiktok", handle=f"page.{index}")
        _account(SimpleNamespace(tenant=record.tenant, user=record.user, influencer=parent), handle=f"facebook.{index}")
    inactive = _account(record, "youtube", "inactive", is_active=False)
    other = _records("other")
    _account(other, "instagram", "foreign")
    assert record.client.get("/api/internal/influencers/?platform=Facebook").data["data"]["count"] == 12
    assert record.client.get("/api/internal/influencers/?platform=TikTok").data["data"]["count"] == 13
    assert record.client.get("/api/internal/influencers/?platform=youtube").data["data"]["count"] == 0
    assert record.client.get("/api/internal/influencers/?platform=instagram").data["data"]["count"] == 0
    counts = []
    for size in (1, 10):
        with CaptureQueriesContext(connection) as queries:
            response = record.client.get(f"/api/internal/influencers/?page_size={size}")
        assert response.status_code == 200
        assert len(response.data["data"]["results"]) == size
        counts.append(len(queries))
        child_queries = [item["sql"] for item in queries if "influencers_influencerplatformaccount" in item["sql"]]
        assert len(child_queries) == 1
        assert " IN " in child_queries[0]
    assert counts[1] <= counts[0] + 1
    inactive.refresh_from_db()
    assert not inactive.is_active


def test_legacy_identity_patch_contract_is_not_frozen_by_phase1():
    record = _records(external_id="OldID")
    response = record.client.patch(f"/api/internal/influencers/{record.influencer.pk}/", {"handle": "legacy.changed", "profile": {"external_influencer_id": "LegacyChangedID"}}, format="json", HTTP_IF_MATCH=record.influencer.updated_at.isoformat())
    assert response.status_code == 200, response.data
    record.influencer.refresh_from_db()
    record.profile.refresh_from_db()
    assert record.influencer.handle == "legacy.changed" and record.profile.external_influencer_id == "LegacyChangedID"
    assert "handle" not in response.data["data"]


@pytest.mark.parametrize("payload", [{"handle": "rewrite"}, {"platform": "instagram"}, {"profile": {"external_influencer_id": "RewriteID"}}])
def test_legacy_identity_rewrite_is_rejected_once_any_platform_slot_exists(payload):
    record = _records()
    _account(record)
    response = record.client.patch(f"/api/internal/influencers/{record.influencer.pk}/", payload, format="json", HTTP_IF_MATCH=record.influencer.updated_at.isoformat())
    assert response.status_code == 400
    record.influencer.refresh_from_db()
    assert record.influencer.platform == "tiktok" and record.influencer.handle == "primary.creator"
    record.influencer.handle = "rewrite"
    with pytest.raises(DjangoValidationError):
        record.influencer.save()


def test_new_virtual_primary_cannot_bypass_an_existing_child_reservation():
    record = _records()
    _account(record)
    response = record.client.post("/api/internal/influencers/?include_form=true", {
        "code": "conflicting-virtual", "name": "Conflict", "platform": "facebook", "handle": "SECONDARY.CREATOR",
        "profile": {}, "contacts": [], "platform_accounts": [],
    }, format="json")
    assert response.status_code == 400
    assert not Influencer.objects.filter(code="conflicting-virtual").exists()


def test_legacy_duplicate_fanout_cannot_rewrite_a_siblings_materialized_identity():
    record = _records()
    duplicate = Influencer.objects.create(tenant=record.tenant, code="legacy-duplicate", name="Duplicate", platform="tiktok", handle=record.influencer.handle)
    child = _account(record, "tiktok", record.influencer.handle)
    response = record.client.patch(f"/api/internal/influencers/{duplicate.pk}/", {"handle": "rewrite"}, format="json", HTTP_IF_MATCH=duplicate.updated_at.isoformat())
    assert response.status_code == 400
    child.refresh_from_db()
    record.influencer.refresh_from_db()
    duplicate.refresh_from_db()
    assert child.handle == record.influencer.handle == duplicate.handle == "primary.creator"
