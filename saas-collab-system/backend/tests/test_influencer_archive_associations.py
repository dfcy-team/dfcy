from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
import json

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection, migrations, models
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError
from django.http import Http404
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers import archive_associations as associations
from apps.influencers import platform_accounts as aggregate
from apps.influencers.models import (
    BdSampleAttributionSnapshot, InfluenceArchiveGroup, InfluenceArchiveMembership,
    Influencer, InfluencerContact, InfluencerPlatformAccount, InfluencerProfile,
    InfluencerRestriction, OutreachTarget, OutreachTask, SampleFulfillment, VideoResult,
    influencer_has_active_restriction, influencer_identity_queryset,
)
from apps.influencers.services import set_influencer_blacklist
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db
SUMMARY_FIELDS = {"id", "code", "platform", "nickname_id", "account_nickname", "updated_at"}
GROUP_FIELDS = {"related_archives", "archive_group_id", "group_version"}
SNAPSHOT_MODELS = (
    Influencer, InfluencerProfile, InfluencerContact, InfluencerPlatformAccount,
    InfluenceArchiveGroup, InfluenceArchiveMembership, OperationLog,
)


def _role(user, code, permissions, scope=DataScope.ScopeType.ALL):
    role = Role.objects.create(tenant=user.tenant, code=code, name=code)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    for code in permissions:
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code, "module": "influencers", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope, config={})


def _records(code="archives", permissions=("influencers.view", "influencers.manage"), scope=DataScope.ScopeType.ALL):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"{code}-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    _role(user, "archives", permissions, scope)
    source = Influencer.objects.create(tenant=tenant, code=f"{code}-source", name="Original raw name", platform="tiktok", handle="source.creator")
    profile = InfluencerProfile.objects.create(tenant=tenant, influencer=source, display_name="Source nickname", external_influencer_id="SourceID")
    client = APIClient()
    client.force_authenticate(user)
    return SimpleNamespace(tenant=tenant, user=user, source=source, profile=profile, client=client)


def _archive(code="new-facebook", platform="facebook"):
    return {
        "code": code, "platform": platform, "nickname_id": f"{code}.creator", "account_nickname": "Independent nickname",
        "profile": {"external_influencer_id": f"{code}-ID", "level": "independent"},
        "contacts": [{"channel": "email", "value": f"{code}@example.test", "is_primary": True}],
    }


def _url(source_id):
    return f"/api/internal/influencers/{source_id}/related-archives/"


def _form_url(source_id):
    return f"/api/internal/influencers/{source_id}/?include_form=true"


def _post(record, archive=None, source=None, version=None):
    source = source or record.source
    return record.client.post(
        _url(source.pk), {"archive": archive or _archive()}, format="json",
        HTTP_IF_MATCH=version or source.updated_at.isoformat(),
    )


def _snapshot():
    return {model.__name__: list(model.objects.order_by("pk").values()) for model in SNAPSHOT_MODELS}


def _group(record):
    return InfluenceArchiveGroup.objects.create(tenant=record.tenant, created_by=record.user, updated_by=record.user)


def test_0031_adds_only_two_tables_without_backfill_or_parent_fields():
    migration = import_module("apps.influencers.migrations.0031_influence_archive_associations").Migration
    assert ("influencers", "0029_primary_identity_indexes") in migration.dependencies
    assert len(migration.operations) == 2
    assert all(isinstance(operation, migrations.CreateModel) for operation in migration.operations)
    assert {operation.name for operation in migration.operations} == {"InfluenceArchiveGroup", "InfluenceArchiveMembership"}
    fields = dict(migration.operations[1].fields)
    assert fields["influencer"].unique
    assert fields["influencer"].remote_field.on_delete is models.PROTECT
    assert fields["group"].remote_field.on_delete is models.PROTECT
    assert not {"parent", "archive_group", "archive_group_id"}.intersection(field.name for field in Influencer._meta.local_fields)
    assert not InfluenceArchiveGroup.objects.exists() and not InfluenceArchiveMembership.objects.exists()


def test_complete_create_and_symmetric_self_including_read_contract():
    record = _records()
    source_before = record.source.updated_at
    response = _post(record)
    assert response.status_code == 201, response.data
    form = response.data["data"]
    created = Influencer.objects.get(pk=form["id"])
    assert created.pk != record.source.pk and created.platform == "facebook"
    assert form["nickname_id"] == "new-facebook.creator" and form["account_nickname"] == "Independent nickname"
    assert form["profile"]["external_influencer_id"] == "new-facebook-ID" and form["contacts"][0]["value"] == "new-facebook@example.test"
    assert {"profile", "contacts", "platform_accounts", "updated_at"} | GROUP_FIELDS <= set(form)
    assert form["archive_group_id"] is not None and form["group_version"] == 1
    assert [row["id"] for row in form["related_archives"]] == [record.source.pk, created.pk]
    assert all(set(row) == SUMMARY_FIELDS for row in form["related_archives"])
    for source in (record.source, created):
        read = record.client.get(_url(source.pk))
        assert read.status_code == 200
        assert set(read.data["data"]) == {"results", "archive_group_id", "group_version"}
        assert read.data["data"]["results"] == form["related_archives"]
        reopened = record.client.get(_form_url(source.pk))
        assert reopened.status_code == 200
        assert reopened.data["data"]["related_archives"] == form["related_archives"]
    record.source.refresh_from_db()
    assert record.source.updated_at > source_before
    assert record.source.name == "Original raw name" and record.source.handle == "source.creator"
    assert not InfluencerPlatformAccount.objects.exists()
    group = InfluenceArchiveGroup.objects.get()
    assert group.created_by == record.user and group.updated_by == record.user
    assert all(member.created_by == record.user for member in group.memberships.all())
    log = OperationLog.objects.get(action="related_archive_create")
    assert log.after_data == {
        "source_id": record.source.pk, "archive_id": created.pk, "archive_group_id": group.pk,
        "member_ids": [record.source.pk, created.pk], "group_version": 1, "outcome": "created",
    }
    audit = json.dumps([log.before_data, log.after_data])
    assert "creator" not in audit and "nickname" not in audit and "SourceID" not in audit


def test_ungrouped_form_and_standalone_create_return_self_only_without_historical_association():
    record = _records()
    Influencer.objects.create(tenant=record.tenant, code="historical-facebook", name=record.source.name, platform="facebook", handle=record.source.handle)
    for source_id in (record.source.pk,):
        form = record.client.get(_form_url(source_id)).data["data"]
        assert form["archive_group_id"] is None and form["group_version"] is None
        assert [row["id"] for row in form["related_archives"]] == [source_id]
        assert record.client.get(_url(source_id)).data["data"]["results"] == form["related_archives"]
    response = record.client.post("/api/internal/influencers/?include_form=true", _archive(), format="json")
    assert response.status_code == 201, response.data
    form = response.data["data"]
    assert form["archive_group_id"] is None and form["group_version"] is None
    assert [row["id"] for row in form["related_archives"]] == [form["id"]]
    assert not InfluenceArchiveGroup.objects.exists() and not InfluenceArchiveMembership.objects.exists()


@pytest.mark.parametrize("provided", [None, "", "   "])
def test_related_create_generates_code_and_keeps_stale_retry_protection(provided):
    record = _records()
    original = record.source.updated_at.isoformat()
    archive = _archive()
    archive.pop("code")
    if provided is not None:
        archive["code"] = provided
    response = _post(record, archive, version=original)
    assert response.status_code == 201, response.data
    form = response.data["data"]
    assert form["code"].startswith("DRDA-") and len(form["code"]) == 37
    assert len(form["related_archives"]) == 2
    before = _snapshot()
    retry = _post(record, archive, version=original)
    assert retry.status_code == 409 and _snapshot() == before
    record.source.refresh_from_db()
    assert record.source.code == "archives-source" and record.source.handle == "source.creator"


def test_related_create_keeps_arbitrary_profile_reference_as_text():
    record = _records()
    archive = _archive()
    archive.pop("code")
    archive["profile"]["profile_url"] = "123 / 主页备注，不是网址"
    response = _post(record, archive)
    assert response.status_code == 201, response.data
    assert response.data["data"]["profile"]["profile_url"] == archive["profile"]["profile_url"]
    record.profile.refresh_from_db()
    assert record.profile.profile_url == ""
    assert len(response.data["data"]["related_archives"]) == 2


def test_manage_only_form_and_create_are_allowed_but_related_read_requires_view():
    record = _records(permissions=("influencers.manage",))
    assert record.client.get(_form_url(record.source.pk)).status_code == 200
    assert record.client.get(_url(record.source.pk)).status_code == 403
    response = _post(record)
    assert response.status_code == 201
    assert len(response.data["data"]["related_archives"]) == 2
    with pytest.raises(PermissionDenied):
        associations.get_related_archives(user=record.user, influencer_id=record.source.pk)


@pytest.mark.parametrize("actor", ["external", "rpa", "inactive", "no_permission", "own", "department", "department_tree", "custom", "unknown"])
def test_request_and_service_actor_scope_denials_leave_zero_rows(actor):
    scope = actor if actor in {"own", "department", "department_tree", "custom", "unknown"} else DataScope.ScopeType.ALL
    record = _records(permissions=() if actor == "no_permission" else ("influencers.view", "influencers.manage"), scope=scope)
    if actor in {"external", "rpa"}:
        record.user.user_type = actor
        record.user.save(update_fields=["user_type"])
    if actor == "inactive":
        record.user.is_active = False
        record.user.save(update_fields=["is_active"])
    before = _snapshot()
    assert record.client.get(_url(record.source.pk)).status_code == 403
    assert record.client.get(_form_url(record.source.pk)).status_code == 403
    assert _post(record).status_code == 403
    with pytest.raises(PermissionDenied):
        associations.get_related_archives(user=record.user, influencer_id=record.source.pk)
    with pytest.raises(PermissionDenied):
        associations.create_related_archive(user=record.user, source_id=record.source.pk, archive=_archive(), expected_updated_at=record.source.updated_at)
    assert _snapshot() == before


def test_view_only_user_cannot_create_or_access_form_and_other_role_all_scope_cannot_widen_manage():
    record = _records(permissions=("influencers.view",))
    assert record.client.get(_url(record.source.pk)).status_code == 200
    assert record.client.get(_form_url(record.source.pk)).status_code == 403
    assert _post(record).status_code == 403
    _role(record.user, "manage-own", ("influencers.manage",), DataScope.ScopeType.OWN)
    assert _post(record).status_code == 403
    with pytest.raises(PermissionDenied):
        associations.create_related_archive(user=record.user, source_id=record.source.pk, archive=_archive(), expected_updated_at=record.source.updated_at)
    assert not InfluenceArchiveMembership.objects.exists()


def test_anonymous_and_foreign_source_requests_and_services_are_denied():
    record = _records()
    foreign = _records("foreign")
    before = _snapshot()
    assert record.client.get(_url(foreign.source.pk)).status_code == 404
    assert record.client.get(_form_url(foreign.source.pk)).status_code == 404
    assert _post(record, source=foreign.source).status_code == 404
    with pytest.raises(Http404):
        associations.create_related_archive(user=record.user, source_id=foreign.source.pk, archive=_archive(), expected_updated_at=foreign.source.updated_at)
    with pytest.raises(Http404):
        associations.get_related_archives(user=record.user, influencer_id=foreign.source.pk)
    assert APIClient().get(_url(record.source.pk)).status_code in (401, 403)
    assert _snapshot() == before


def test_grouped_summaries_are_tenant_isolated_even_with_same_platform_usernames():
    record = _records()
    foreign = _records("foreign")
    first = _post(record)
    second = _post(foreign)
    assert first.status_code == second.status_code == 201
    own_ids = [record.source.pk, first.data["data"]["id"]]
    foreign_ids = [foreign.source.pk, second.data["data"]["id"]]
    assert first.data["data"]["archive_group_id"] != second.data["data"]["archive_group_id"]
    for source_id in own_ids:
        data = record.client.get(_url(source_id)).data["data"]
        assert [row["id"] for row in data["results"]] == own_ids
        assert not set(foreign_ids).intersection(row["id"] for row in data["results"])
    for source_id in foreign_ids:
        assert record.client.get(_url(source_id)).status_code == 404


def test_manage_all_scope_cannot_widen_own_scope_nickname_read():
    record = _records(permissions=("influencers.manage",))
    _role(record.user, "view-own", ("influencers.view",), DataScope.ScopeType.OWN)
    assert record.client.get(_form_url(record.source.pk)).status_code == 200
    assert record.client.get(_url(record.source.pk)).status_code == 403
    with pytest.raises(PermissionDenied):
        associations.get_related_archives(user=record.user, influencer_id=record.source.pk)


@pytest.mark.parametrize("platform", [None, "", " ", "unsupported"])
def test_related_platform_is_explicit_required_and_supported(platform):
    record = _records()
    payload = _archive(platform=platform)
    if platform is None:
        payload.pop("platform")
    before = _snapshot()
    assert _post(record, payload).status_code == 400
    assert _snapshot() == before


@pytest.mark.parametrize("platform", ["TiKToK", " tiktok "])
def test_same_platform_related_archive_is_independent_and_platform_is_normalized(platform):
    record = _records()
    source_identity = (record.source.code, record.source.handle, record.profile.external_influencer_id)
    response = _post(record, _archive("another-tiktok", platform))
    assert response.status_code == 201, response.data
    form = response.data["data"]
    assert form["id"] != record.source.pk and form["platform"] == "tiktok"
    assert form["nickname_id"] == "another-tiktok.creator"
    assert {row["id"] for row in form["related_archives"]} == {record.source.pk, form["id"]}
    record.source.refresh_from_db()
    record.profile.refresh_from_db()
    assert (record.source.code, record.source.handle, record.profile.external_influencer_id) == source_identity


def test_multiple_facebook_accounts_can_be_created_from_the_same_facebook_source():
    record = _records()
    record.source.platform = "facebook"
    record.source.save(update_fields=["platform"])
    expected_ids = {record.source.pk}
    for index in range(3):
        record.source.refresh_from_db()
        response = _post(record, _archive(f"facebook-{index}", "facebook"))
        assert response.status_code == 201, response.data
        form = response.data["data"]
        expected_ids.add(form["id"])
        assert form["group_version"] == index + 1
        assert {row["id"] for row in form["related_archives"]} == expected_ids
        for source_id in expected_ids:
            read = record.client.get(_url(source_id))
            assert read.status_code == 200
            assert {row["id"] for row in read.data["data"]["results"]} == expected_ids
    assert Influencer.objects.count() == 4 and InfluenceArchiveGroup.objects.count() == 1
    assert InfluenceArchiveMembership.objects.count() == 4


def test_all_group_platforms_remain_available_and_all_members_advance():
    record = _records()
    first = _post(record, _archive(platform=" Facebook "))
    assert first.status_code == 201
    facebook = Influencer.objects.get(pk=first.data["data"]["id"])
    record.source.refresh_from_db()
    second = _post(record, _archive("new-instagram", "instagram"))
    assert second.status_code == 201 and second.data["data"]["group_version"] == 2
    instagram = Influencer.objects.get(pk=second.data["data"]["id"])
    before = {row.pk: row.updated_at for row in Influencer.objects.all()}
    facebook.refresh_from_db()
    third = _post(record, _archive("another-facebook", "facebook"), source=facebook)
    assert third.status_code == 201 and third.data["data"]["group_version"] == 3
    assert [row["id"] for row in third.data["data"]["related_archives"]] == sorted(Influencer.objects.values_list("pk", flat=True))
    for member in Influencer.objects.filter(pk__in=before):
        assert member.updated_at > before[member.pk]
    assert facebook.platform == "facebook" and InfluenceArchiveGroup.objects.count() == 1


@pytest.mark.parametrize("version", [None, "", "not-a-date", "2026-99-99T00:00:00Z", "2026-10-10T00:00:00", "1", "W/invalid"])
def test_missing_or_malformed_source_cas_is_400_without_writes(version):
    record = _records()
    before = _snapshot()
    headers = {} if version is None else {"HTTP_IF_MATCH": version}
    response = record.client.post(_url(record.source.pk), {"archive": _archive()}, format="json", **headers)
    assert response.status_code == 400, response.data
    assert _snapshot() == before


def test_replay_and_stale_forms_return_conflict_without_extra_rows():
    record = _records()
    original = record.source.updated_at.isoformat()
    assert _post(record, version=f'"{original}"').status_code == 201
    before = _snapshot()
    assert _post(record, version=original).status_code == 409
    assert _post(record, _archive("different-retry", "instagram"), version=original).status_code == 409
    assert record.client.patch(_form_url(record.source.pk), {"name": "stale edit"}, format="json", HTTP_IF_MATCH=original).status_code == 409
    assert _snapshot() == before


@pytest.mark.parametrize("field,value", [
    ("id", 1), ("tenant_id", 1), ("status", "active"), ("created_at", "server-owned"),
    ("updated_at", "server-owned"), ("platform_accounts", []), ("archive_group_id", 1),
    ("group_version", 1), ("related_archives", []), ("group", {}), ("parent", 1), ("created_by", 1),
])
def test_related_create_rejects_server_owned_and_child_or_link_metadata(field, value):
    record = _records()
    payload = {**_archive(), field: value}
    before = _snapshot()
    assert _post(record, payload).status_code == 400
    assert _snapshot() == before


@pytest.mark.parametrize("payload", [
    {"profile": {"id": 1}}, {"profile": {"tenant": 1}}, {"contacts": [{"id": 1, "channel": "email", "value": "new@example.test"}]},
    {"profile": None}, {"contacts": None}, {"contacts": [1]}, {"profile": []},
])
def test_related_create_rejects_nested_server_fields_and_invalid_sections(payload):
    record = _records()
    before = _snapshot()
    assert _post(record, {**_archive(), **payload}).status_code == 400
    assert _snapshot() == before


@pytest.mark.parametrize("body", [[], None, {}, {"archive": None}, {"archive": {}, "existing_id": 1}, {"existing_id": 1}])
def test_related_request_requires_only_archive_object_and_has_no_link_or_unlink_methods(body):
    record = _records()
    before = _snapshot()
    assert record.client.post(_url(record.source.pk), body, format="json", HTTP_IF_MATCH=record.source.updated_at.isoformat()).status_code == 400
    for method in (record.client.patch, record.client.put, record.client.delete):
        assert method(_url(record.source.pk), {}, format="json").status_code == 405
    assert _snapshot() == before


@pytest.mark.parametrize("restriction_source", ["direct", "tiktok_duplicate"])
def test_restricted_source_cannot_bypass_policy_by_creating_other_platform(restriction_source):
    record = _records()
    restricted = record.source
    if restriction_source == "tiktok_duplicate":
        restricted = Influencer.objects.create(tenant=record.tenant, code="duplicate-tiktok", name="Duplicate", platform="TikTok", handle=record.source.handle)
    InfluencerRestriction.objects.create(tenant=record.tenant, influencer=restricted, created_by=record.user)
    before = _snapshot()
    assert _post(record).status_code == 400
    assert _snapshot() == before


def test_blacklist_remains_per_archive_with_existing_tiktok_identity_behavior():
    record = _records()
    duplicate = Influencer.objects.create(tenant=record.tenant, code="duplicate-tiktok", name="Duplicate", platform="TikTok", handle=record.source.handle)
    response = _post(record)
    facebook = Influencer.objects.get(pk=response.data["data"]["id"])
    set_influencer_blacklist(user=record.user, influencer=record.source, blacklisted=True, reason="synthetic restriction")
    assert influencer_has_active_restriction(record.source) and influencer_has_active_restriction(duplicate)
    assert not influencer_has_active_restriction(facebook)
    assert not InfluencerRestriction.objects.filter(influencer=facebook).exists()
    assert record.client.get(f"/api/internal/influencers/{facebook.pk}/").data["data"]["is_blacklisted"] is False
    assert _post(record, _archive("new-instagram", "instagram"), source=facebook).status_code == 201


@pytest.mark.parametrize("point", ["post_create", "source_member", "new_member", "aggregate_audit", "association_audit"])
def test_fault_after_real_writes_rolls_back_parent_profile_contacts_members_and_audits(monkeypatch, point):
    record = _records()
    before = _snapshot()

    def fail():
        raise RuntimeError(f"synthetic {point} failure")

    if point == "post_create":
        original = associations.save_influencer_aggregate

        def save(**kwargs):
            original(**kwargs)
            fail()

        monkeypatch.setattr(associations, "save_influencer_aggregate", save)
    elif point in {"source_member", "new_member"}:
        original = InfluenceArchiveMembership.save

        def save(member, *args, **kwargs):
            original(member, *args, **kwargs)
            if (member.influencer_id == record.source.pk) == (point == "source_member"):
                fail()

        monkeypatch.setattr(InfluenceArchiveMembership, "save", save)
    else:
        module = aggregate if point == "aggregate_audit" else associations
        original = module.write_operation_log

        def audit(**kwargs):
            original(**kwargs)
            fail()

        monkeypatch.setattr(module, "write_operation_log", audit)
    with pytest.raises(RuntimeError, match="synthetic"):
        _post(record)
    assert _snapshot() == before


@pytest.mark.parametrize("model", [Influencer, InfluenceArchiveGroup])
def test_member_or_group_cas_conflict_rolls_back_expanded_existing_group(monkeypatch, model):
    record = _records()
    assert _post(record).status_code == 201
    record.source.refresh_from_db()
    before = _snapshot()
    original = QuerySet.update

    def update(queryset, **kwargs):
        if queryset.model is model and "updated_at" in kwargs:
            return 0
        return original(queryset, **kwargs)

    monkeypatch.setattr(QuerySet, "update", update)
    assert _post(record, _archive("new-instagram", "instagram")).status_code == 409
    assert _snapshot() == before


def test_post_audit_fault_rolls_back_all_existing_group_versions_and_response_fault_rolls_back(monkeypatch):
    from apps.influencers.serializers import InfluencerFormSerializer

    record = _records()
    assert _post(record).status_code == 201
    record.source.refresh_from_db()
    before = _snapshot()
    original = associations.write_operation_log

    def audit(**kwargs):
        original(**kwargs)
        raise RuntimeError("synthetic post-audit failure")

    with monkeypatch.context() as patch:
        patch.setattr(associations, "write_operation_log", audit)
        with pytest.raises(RuntimeError, match="synthetic"):
            _post(record, _archive("new-instagram", "instagram"))
    assert _snapshot() == before

    def serialize(*args, **kwargs):
        raise RuntimeError("synthetic response failure")

    monkeypatch.setattr(InfluencerFormSerializer, "to_representation", serialize)
    with pytest.raises(RuntimeError, match="synthetic"):
        _post(record, _archive("new-instagram", "instagram"))
    assert _snapshot() == before


def test_tenant_then_ordered_members_then_group_locks_and_monotonic_versions_without_save_fanout(monkeypatch):
    record = _records()
    assert _post(record).status_code == 201
    record.source.refresh_from_db()
    before = {row.pk: row.updated_at for row in Influencer.objects.all()}
    duplicate = Influencer.objects.create(tenant=record.tenant, code="unrelated-duplicate", name="Duplicate", platform="tiktok", handle=record.source.handle)
    duplicate_before = duplicate.updated_at
    locks = []
    original = QuerySet.select_for_update

    def lock(queryset, *args, **kwargs):
        locks.append(queryset.model)
        return original(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", lock)
    monkeypatch.setattr(associations.timezone, "now", lambda: min(before.values()) - timedelta(seconds=1))
    response = _post(record, _archive("new-instagram", "instagram"))
    assert response.status_code == 201, response.data
    assert locks[:3] == [Tenant, Influencer, InfluenceArchiveGroup]
    for row in Influencer.objects.filter(pk__in=before):
        assert row.updated_at == max(before.values()) + timedelta(microseconds=1)
    duplicate.refresh_from_db()
    assert duplicate.updated_at == duplicate_before and duplicate.handle == "source.creator"
    assert InfluenceArchiveGroup.objects.get().version == 2


def test_ordinary_and_nickname_responses_never_expose_group_or_other_member_usernames():
    record = _records()
    assert _post(record).status_code == 201
    record.source.refresh_from_db()
    urls = (
        "/api/internal/influencers/", f"/api/internal/influencers/{record.source.pk}/",
        "/api/internal/influencers/?include_nickname_id=true", f"/api/internal/influencers/{record.source.pk}/?include_nickname_id=true",
    )
    for url in urls:
        response = record.client.get(url)
        assert response.status_code == 200
        data = response.data["data"]
        rows = data["results"] if "results" in data else [data]
        for row in rows:
            assert not GROUP_FIELDS.intersection(row) and "handle" not in row and "platform_accounts" not in row
    ordinary = record.client.patch(f"/api/internal/influencers/{record.source.pk}/", {"name": "Ordinary edit"}, format="json", HTTP_IF_MATCH=record.source.updated_at.isoformat())
    assert ordinary.status_code == 200 and not GROUP_FIELDS.intersection(ordinary.data["data"])


def test_nonzero_legacy_children_and_business_fks_statistics_and_usernames_are_unchanged():
    record = _records()
    child = InfluencerPlatformAccount.objects.create(
        tenant=record.tenant, influencer=record.source, platform="facebook", handle="legacy.child",
        display_name="Legacy child", created_by=record.user, updated_by=record.user,
    )
    contact = InfluencerContact.objects.create(tenant=record.tenant, influencer=record.source, channel="email", value="source@example.test", created_by=record.user)
    platform = PlatformMaster.objects.create(tenant=record.tenant, code="synthetic-tiktok", name="TikTok", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=record.tenant, platform=platform, code="synthetic-store", name="Store", country_code="PH", currency="PHP")
    task = OutreachTask.objects.create(tenant=record.tenant, influencer=record.source, task_no="TASK-original", store=store, dispatcher=record.user, owner=record.user)
    target = OutreachTarget.objects.create(tenant=record.tenant, task=task, influencer=record.source)
    sample = SampleFulfillment.objects.create(
        tenant=record.tenant, influencer=record.source, outreach_task=task, outreach_target=target,
        fulfillment_no="SAMPLE-original", request_key="synthetic-original", request_hash="synthetic-hash", store=store, owner=record.user,
    )
    attribution = BdSampleAttributionSnapshot.objects.create(
        tenant=record.tenant, influencer=record.source, fulfillment=sample, owner=record.user, store=store,
        creator_username=record.source.handle, shop_abbr=store.code, site="PH", sampled_at=sample.created_at,
        sample_status="pending", currency="PHP", pricing_status="pending",
    )
    video = VideoResult.objects.create(tenant=record.tenant, influencer=record.source, store=store, content_type="video", platform="tiktok", external_content_id="original-video", metric_date=date(2026, 10, 1), currency="PHP", views=42)
    record.profile.historical_gmv = Decimal("123.0000")
    record.profile.save()
    original_models = (InfluencerProfile, InfluencerContact, InfluencerPlatformAccount, OutreachTask, OutreachTarget, SampleFulfillment, BdSampleAttributionSnapshot, VideoResult)
    before = {model: list(model.objects.values()) for model in original_models}
    identity_before = list(influencer_identity_queryset(record.source).values_list("pk", flat=True))
    response = _post(record)
    assert response.status_code == 201, response.data
    created = Influencer.objects.get(pk=response.data["data"]["id"])
    # An ordinary form edit intentionally omits the legacy child section.
    record.source.refresh_from_db()
    edited = record.client.patch(_form_url(record.source.pk), {"category": "updated"}, format="json", HTTP_IF_MATCH=record.source.updated_at.isoformat())
    assert edited.status_code == 200
    for model in original_models:
        original_ids = [row["id"] for row in before[model]]
        assert list(model.objects.filter(pk__in=original_ids).values()) == before[model]
    for obj in (child, contact, task, target, sample, attribution, video):
        obj.refresh_from_db()
        assert obj.influencer_id == record.source.pk
    assert list(influencer_identity_queryset(record.source).values_list("pk", flat=True)) == identity_before
    assert not created.platform_accounts.exists() and not created.video_results.exists()
    assert created.profile.historical_gmv == InfluencerProfile._meta.get_field("historical_gmv").default
    assert record.source.name == "Original raw name" and attribution.creator_username == "source.creator"
    assert "related_archives" in edited.data["data"] and len(edited.data["data"]["platform_accounts"]) == 2


@pytest.mark.parametrize("model", [InfluenceArchiveGroup, InfluenceArchiveMembership])
def test_models_block_bulk_update_create_delete_and_instance_mutation(model):
    record = _records()
    group = _group(record)
    member = InfluenceArchiveMembership.objects.create(tenant=record.tenant, group=group, influencer=record.source, created_by=record.user)
    instance = group if model is InfluenceArchiveGroup else member
    with pytest.raises(DjangoValidationError):
        instance.save()
    with pytest.raises(DjangoValidationError):
        instance.save_base(raw=True)
    with pytest.raises(DjangoValidationError):
        instance.delete()
    with pytest.raises(DjangoValidationError):
        model.objects.filter(pk=instance.pk).delete()
    with pytest.raises(DjangoValidationError):
        model.objects.filter(pk=instance.pk).update(tenant_id=record.tenant.pk)
    with pytest.raises(DjangoValidationError):
        model.objects.bulk_create([])
    with pytest.raises(DjangoValidationError):
        model.objects.bulk_update([instance], ["tenant"])


@pytest.mark.parametrize("field", ["tenant", "group", "influencer", "created_by"])
def test_membership_validates_tenant_consistency_and_rejects_reassignment(field):
    record = _records()
    foreign = _records("foreign")
    group = _group(record)
    foreign_group = _group(foreign)
    values = {"tenant": record.tenant, "group": group, "influencer": record.source, "created_by": record.user}
    foreign_value = {"tenant": foreign.tenant, "group": foreign_group, "influencer": foreign.source, "created_by": foreign.user}[field]
    with pytest.raises(DjangoValidationError):
        InfluenceArchiveMembership.objects.create(**{**values, field: foreign_value})
    member = InfluenceArchiveMembership.objects.create(**values)
    setattr(member, field, foreign_value)
    with pytest.raises(DjangoValidationError):
        member.save()


@pytest.mark.parametrize("field", ["created_by", "updated_by"])
def test_group_actor_tenant_consistency_is_enforced_for_save_and_raw_save(field):
    record = _records()
    foreign = _records("foreign")
    values = {"tenant": record.tenant, "created_by": record.user, "updated_by": record.user, field: foreign.user}
    with pytest.raises(DjangoValidationError):
        InfluenceArchiveGroup.objects.create(**values)
    with pytest.raises(DjangoValidationError):
        InfluenceArchiveGroup(**values).save_base(raw=True)


def test_unique_membership_and_protected_group_parent_actor_references():
    record = _records()
    group = _group(record)
    other_group = _group(record)
    InfluenceArchiveMembership.objects.create(tenant=record.tenant, group=group, influencer=record.source, created_by=record.user)
    with pytest.raises(DjangoValidationError):
        InfluenceArchiveMembership.objects.create(tenant=record.tenant, group=other_group, influencer=record.source, created_by=record.user)
    for obj in (record.source, record.user):
        with pytest.raises(ProtectedError):
            obj.delete()
    with pytest.raises(DjangoValidationError):
        InfluenceArchiveGroup.objects.create(tenant=record.tenant, created_by=record.user, updated_by=record.user, version=2)


@pytest.mark.django_db(transaction=True)
def test_real_concurrent_duplicate_create_uses_one_source_cas():
    if not connection.features.has_select_for_update:
        pytest.skip("Requires an isolated row-locking database; SQLite cannot prove the tenant lock race.")
    record = _records()
    barrier = Barrier(2)
    version = record.source.updated_at

    def create():
        close_old_connections()
        try:
            user = CustomUser.objects.get(pk=record.user.pk)
            barrier.wait(timeout=10)
            try:
                saved = associations.create_related_archive(user=user, source_id=record.source.pk, archive=_archive(), expected_updated_at=version)
                return (201, saved.pk)
            except aggregate.InfluencerFormConflict:
                return (409, None)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(status for status, _ in results) == [201, 409]
    assert Influencer.objects.count() == 2 and InfluencerProfile.objects.count() == 2 and InfluencerContact.objects.count() == 1
    assert InfluenceArchiveGroup.objects.count() == 1 and InfluenceArchiveMembership.objects.count() == 2
    assert OperationLog.objects.filter(action="related_archive_create").count() == 1
