from collections import Counter
import json
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import CustomUser
from apps.influencers import tiktok_dataset_import as importer
from apps.influencers.models import (
    ExternalSourceRecord,
    ImportBatch,
    InfluencerProfile,
    TikTokShopVideo,
    TikTokVideoDailyMetric,
    AffiliateOrderSnapshot,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


@pytest.fixture
def trial(monkeypatch, tmp_path):
    tenant = Tenant.objects.create(name="TikTok dataset trial", code="tk-dataset-trial")
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="tiktok",
        name="TikTok Shop",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="tk-ph-trial",
        name="TikTok PH trial",
        external_store_id="shop-placeholder-1",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    actor = CustomUser.objects.create_user(
        username="tk-dataset-operator",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        password="placeholder-only",
    )
    role = Role.objects.create(tenant=tenant, code="integration_admin", name="TikTok dataset importer")
    UserRole.objects.create(tenant=tenant, user=actor, role=role)
    for code in ("influencers.manage", "integrations.run_live_readonly"):
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "test", "action": "manage"},
        )
        role.permissions.add(permission)
        DataScope.objects.get_or_create(
            tenant=tenant,
            role=role,
            scope_type=DataScope.ScopeType.ALL,
            defaults={"config": {"all": True}},
        )

    digest = "a" * 64
    artifact = {"manifest": None, "rows": None, "digest": digest}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("placeholder artifact is monkeypatched in unit tests", encoding="utf-8")

    def set_artifact(*, videos=(), statuses=None, tenant_id=None, store_entries=None, extra_rows=()):
        statuses = statuses or {}
        entries = store_entries or [{
            "store_id": store.pk,
            "store_code": store.code,
            "platform_shop_id": store.external_store_id,
            "timezone": store.timezone,
        }]
        artifact_tenant_id = tenant.pk if tenant_id is None else tenant_id
        components = []
        rows = []
        for entry in entries:
            for kind in ("affiliate_orders", "creators", "videos"):
                status = statuses.get((entry["store_id"], kind), statuses.get(kind, "complete"))
                component_rows = []
                if kind == "videos" and status == "complete":
                    component_rows = [
                        {
                            "kind": "videos",
                            "tenant_id": artifact_tenant_id,
                            "store_id": entry["store_id"],
                            "store_code": entry["store_code"],
                            "payload": dict(payload),
                        }
                        for payload in videos
                    ]
                component = {
                    "kind": kind,
                    "store_id": entry["store_id"],
                    "status": status,
                    "row_count": len(component_rows),
                    "request_count": 1,
                }
                if status == "complete":
                    component.update(file=f"store-{entry['store_id']}-{kind}.jsonl", sha256="b" * 64)
                else:
                    component["reason"] = "placeholder_component_failed"
                components.append(component)
                rows.extend(component_rows)
        rows.extend(extra_rows)
        artifact["manifest"] = {
            "schema_version": 1,
            "tenant_id": artifact_tenant_id,
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
            "stores": [dict(entry) for entry in entries],
            "components": components,
        }
        artifact["rows"] = rows
        return artifact

    def fake_loader(path, expected_digest):
        assert path == str(manifest_path)
        assert expected_digest == digest
        return artifact["manifest"], artifact["rows"]

    monkeypatch.setattr(importer, "load_artifact", fake_loader)

    def run(*, limit=20, apply=False, tenant_id=None, store_id=None, actor_id=None):
        return importer.run_import(
            manifest_path=str(manifest_path),
            manifest_sha256=digest,
            tenant_id=tenant.pk if tenant_id is None else tenant_id,
            store_id=store.pk if store_id is None else store_id,
            actor_id=actor.pk if actor_id is None else actor_id,
            limit=limit,
            apply=apply,
        )

    return {
        "tenant": tenant,
        "store": store,
        "actor": actor,
        "role": role,
        "manifest_path": manifest_path,
        "digest": digest,
        "artifact": artifact,
        "set_artifact": set_artifact,
        "run": run,
    }


def _video(video_id="video-1", author_type="AFFILIATE", **overrides):
    payload = {
        "external_video_id": video_id,
        "creator_open_id": "creator-open-id-placeholder",
        "creator_username": "creator-placeholder",
        "creator_nickname": "Nickname must not be saved",
        "author_type": author_type,
        "title": "Placeholder video title",
        "published_at": None,
        "metric_date": "2026-09-02",
        "currency": "PHP",
        "metrics": {"views": None, "gmv": {"amount": None, "currency": None}},
        "canonical_metric_blocker": "nullable_daily_metric_contract_required",
    }
    payload.update(overrides)
    return payload


def test_dry_run_validates_scope_and_writes_nothing(trial):
    trial["set_artifact"](videos=[_video()])

    summary = trial["run"]()

    assert summary["mode"] == "dry-run"
    assert summary["eligible"] == 1
    assert summary["created"] == 0
    assert TikTokShopVideo.objects.count() == 0
    assert ImportBatch.objects.count() == 0
    assert ExternalSourceRecord.objects.count() == 0
    assert TikTokVideoDailyMetric.objects.count() == 0
    assert AffiliateOrderSnapshot.objects.count() == 0
    assert InfluencerProfile.objects.count() == 0


def test_naive_source_time_does_not_become_database_timestamp(trial):
    trial["set_artifact"](videos=[_video(source_published_at="2026-09-02 15:23:01")])
    result = trial["run"](apply=True)
    assert result["created"] == 1
    assert TikTokShopVideo.objects.get().published_at is None
    assert trial["run"](apply=True)["noop"] == 1


@pytest.mark.parametrize("value", ["2026-02-30 15:23:01", "2026-09-02T15:23:01", "2026-09-02 24:23:01"])
def test_invalid_source_time_is_quarantined_without_writes(trial, value):
    trial["set_artifact"](videos=[_video(source_published_at=value)])
    result = trial["run"]()
    assert result["eligible"] == 0
    assert result["reasons"] == {"invalid_source_video_published_at": 1}
    assert TikTokShopVideo.objects.count() == 0


@pytest.mark.parametrize(
    ("author_type", "expected_type"),
    [
        ("OFFICIAL", TikTokShopVideo.VideoType.SELF_OPERATED),
        ("CHANNEL", TikTokShopVideo.VideoType.SELF_OPERATED),
        ("AFFILIATE", TikTokShopVideo.VideoType.CREATOR),
    ],
)
def test_apply_writes_only_video_identity_and_hash_audit(trial, author_type, expected_type):
    trial["set_artifact"](videos=[_video(author_type=author_type)])

    summary = trial["run"](apply=True)

    video = TikTokShopVideo.objects.get()
    source_record = ExternalSourceRecord.objects.get()
    batch = ImportBatch.objects.get()
    assert summary["created"] == 1
    assert summary["eligible"] == 1
    assert video.external_video_id == "video-1"
    assert video.video_type == expected_type
    assert video.creator_id == ""
    assert video.creator_open_id == "creator-open-id-placeholder"
    assert video.creator_username == "creator-placeholder"
    assert video.influencer_id is None
    assert video.title == "Placeholder video title"
    assert video.published_at is None
    assert "Nickname must not be saved" not in str(video.__dict__)
    assert source_record.payload_hash and len(source_record.payload_hash) == 64
    assert "Nickname must not be saved" not in str(source_record.__dict__)
    assert source_record.target_model == "TikTokShopVideo"
    assert source_record.target_id == str(video.pk)
    assert source_record.batch_id == batch.pk
    assert batch.source == "tk_shop_dataset_trial"
    assert batch.manifest_digest == trial["digest"]
    assert batch.status == ImportBatch.Status.COMPLETED
    assert TikTokVideoDailyMetric.objects.count() == 0
    assert AffiliateOrderSnapshot.objects.count() == 0
    assert InfluencerProfile.objects.count() == 0


def test_failed_orders_and_creator_components_do_not_block_complete_videos(trial):
    trial["set_artifact"](
        videos=[_video()],
        statuses={"affiliate_orders": "failed", "creators": "failed", "videos": "complete"},
    )

    summary = trial["run"](apply=True)

    assert summary["created"] == 1
    assert TikTokShopVideo.objects.count() == 1
    assert ExternalSourceRecord.objects.count() == 1


def test_failed_video_component_is_not_promoted(trial):
    trial["set_artifact"](videos=[_video()], statuses={"videos": "failed"})

    summary = trial["run"]()

    assert summary["failed_video_component"] is True
    assert summary["eligible"] == 0
    with pytest.raises(importer.DatasetImportError, match="failed_video_component"):
        trial["run"](apply=True)
    assert TikTokShopVideo.objects.count() == 0
    assert ImportBatch.objects.count() == 0
    assert ExternalSourceRecord.objects.count() == 0


def test_limit_is_capped_and_replay_with_different_limit_is_idempotent(trial):
    trial["set_artifact"](videos=[_video(f"video-{number}") for number in (3, 1, 2)])

    first = trial["run"](limit=1, apply=True)
    second = trial["run"](limit=3, apply=True)
    replay = trial["run"](limit=3, apply=True)

    assert first["created"] == 1
    assert first["deferred"] == 2
    assert second["created"] == 2
    assert second["noop"] == 1
    assert replay["created"] == 0
    assert replay["noop"] == 3
    assert TikTokShopVideo.objects.count() == 3
    assert ExternalSourceRecord.objects.count() == 3
    assert ImportBatch.objects.count() == 2
    assert len({batch.batch_key for batch in ImportBatch.objects.all()}) == 2


def test_limit_over_twenty_is_rejected(trial):
    with pytest.raises(importer.DatasetImportError, match="limit_must_be_between_1_and_20"):
        trial["run"](limit=21)


def test_unknown_author_type_is_quarantined(trial):
    trial["set_artifact"](videos=[
        _video("unknown-author", author_type="UNRECOGNIZED"),
    ])

    summary = trial["run"](apply=True)

    assert summary["eligible"] == 0
    assert summary["quarantined"] == 1
    assert summary["reasons"] == Counter({"unknown_author_type": 1})
    assert TikTokShopVideo.objects.count() == 0
    assert ExternalSourceRecord.objects.count() == 0


def _v2_partial(trial, videos):
    trial["set_artifact"](videos=videos)
    manifest = trial["artifact"]["manifest"]
    manifest["schema_version"] = 2
    for component in manifest["components"]:
        component["days"] = [
            {"date": day, "status": "complete", "expected_count": None,
             "observed_count": component["row_count"] if day == "2026-09-02" else 0,
             "page_count": 1, "pagination_exhausted": True, "reason": "pagination_exhausted"}
            for day in ["2026-09-01", "2026-09-02", "2026-09-03"]
        ]
        if component["kind"] == "videos":
            component["status"] = "partial"
            component["days"][1].update(status="partial", expected_count=len(videos) + 1,
                                         reason="pagination_total_mismatch")


def test_partial_v2_writes_identity_without_metrics_or_attribution(trial):
    _v2_partial(trial, [_video(author_type="", title="x" * 1200)])
    result = trial["run"](apply=True)
    assert result["created"] == 1
    assert result["source_quality"] == "partial"
    assert result["identity_only"] and result["metric_rows_written"] == 0
    video = TikTokShopVideo.objects.get()
    assert video.video_type == "unknown"
    assert video.source_api == "tiktok_shop_identity_partial"
    assert len(video.title) == 1200 and video.influencer_id is None
    assert trial["run"](apply=True)["noop"] == 1
    assert TikTokShopVideo.objects.count() == 1
    assert TikTokVideoDailyMetric.objects.count() == AffiliateOrderSnapshot.objects.count() == 0
    assert trial["artifact"]["manifest"]["components"][-1]["status"] == "partial"


@pytest.mark.parametrize("author_type,expected", [
    ("AFFILIATE_ACCOUNTS", TikTokShopVideo.VideoType.CREATOR),
    ("OFFICIAL_ACCOUNTS", TikTokShopVideo.VideoType.SELF_OPERATED),
    ("MARKETING_ACCOUNTS", TikTokShopVideo.VideoType.UNKNOWN),
])
def test_v2_observed_account_aliases_keep_partial_identity_only(trial, author_type, expected):
    _v2_partial(trial, [_video(author_type=author_type)])
    result = trial["run"](apply=True)
    video = TikTokShopVideo.objects.get()
    assert result["created"] == 1 and result["source_quality"] == "partial"
    assert video.video_type == expected and video.influencer_id is None and video.creator_id == ""
    assert video.source_api == "tiktok_shop_identity_partial"
    assert TikTokVideoDailyMetric.objects.count() == AffiliateOrderSnapshot.objects.count() == InfluencerProfile.objects.count() == 0
    assert trial["run"](apply=True)["noop"] == 1


@pytest.mark.parametrize("author_type", ["AFFILIATE_ACCOUNTS", "OFFICIAL_ACCOUNTS", "MARKETING_ACCOUNTS"])
def test_v1_does_not_accept_v2_account_aliases(trial, author_type):
    trial["set_artifact"](videos=[_video(author_type=author_type)])
    result = trial["run"](apply=True)
    assert result["eligible"] == 0 and result["reasons"] == {"unknown_author_type": 1}
    assert TikTokShopVideo.objects.count() == 0


def test_v2_other_nonempty_author_enum_is_still_quarantined(trial):
    _v2_partial(trial, [_video(author_type="UNRECOGNIZED_ACCOUNTS")])
    result = trial["run"](apply=True)
    assert result["eligible"] == 0 and result["reasons"] == {"unknown_author_type": 1}
    assert TikTokShopVideo.objects.count() == 0


def test_partial_v2_failed_date_cannot_write_identity(trial):
    _v2_partial(trial, [_video()])
    trial["artifact"]["manifest"]["components"][-1]["days"][1].update(status="failed", observed_count=0)
    with pytest.raises(importer.DatasetImportError, match="failed_day_has_rows"):
        trial["run"](apply=True)
    assert TikTokShopVideo.objects.count() == 0


def test_partial_v2_day_count_tampering_is_rejected(trial):
    _v2_partial(trial, [_video()])
    trial["artifact"]["manifest"]["components"][-1]["days"][1]["observed_count"] = 2
    with pytest.raises(importer.DatasetImportError, match="day_observation_count_mismatch"):
        trial["run"](apply=True)
    assert TikTokShopVideo.objects.count() == 0


def test_boolean_schema_cannot_enable_identity_import(trial):
    _v2_partial(trial, [_video()])
    trial["artifact"]["manifest"]["schema_version"] = True
    with pytest.raises(importer.DatasetImportError, match="invalid_manifest_schema"):
        trial["run"](apply=True)
    assert TikTokShopVideo.objects.count() == 0


def test_real_exporter_loader_partial_identity_roundtrip_without_total(trial, tmp_path, monkeypatch):
    from apps.influencers import tiktok_shop_dataset as dataset
    store = trial["store"]
    config = SimpleNamespace(pk=1, credential_id="synthetic", environment="pilot",
                             network_enabled=False, sync_read_enabled=False)
    auth = SimpleNamespace(pk=1, store=store, store_id=store.pk,
                           platform_store_id=store.external_store_id, integration_config=config,
                           shop_cipher="synthetic", scopes=[])

    class SyntheticClient:
        request_count = 0

        def __init__(self, *_):
            pass

        def verify_shop(self):
            pass

        def affiliate_orders(self, *_args, **_kwargs):
            self.last_page_summary = {"status": "complete", "reason": "pagination_exhausted",
                                      "expected_count": 0, "observed_count": 0,
                                      "page_count": 1, "pagination_exhausted": True}
            return [], 1

        def video_day(self, day, **_kwargs):
            partial = day.isoformat() == "2026-09-02"
            rows = [dataset.project_video({"id": "synthetic-video", "title": "x" * 1200}, day.isoformat())] if partial else []
            self.last_page_summary = {"status": "partial" if partial else "complete",
                                      "reason": "pagination_total_mismatch" if partial else "pagination_exhausted",
                                      "expected_count": 2 if partial else None,
                                      "observed_count": len(rows), "page_count": 1,
                                      "pagination_exhausted": True}
            return rows, 1

    directory = tmp_path / "roundtrip"
    manifest, digest = dataset.export_artifact(
        output_dir=directory, actor=trial["actor"], authorizations=[auth],
        start_date="2026-09-01", end_date="2026-09-03", creator_seeds=[],
        staging=True, client_factory=SyntheticClient,
    )
    monkeypatch.setattr(importer, "load_artifact", dataset.load_artifact)
    args = dict(manifest_path=str(directory / "manifest.json"), manifest_sha256=digest,
                tenant_id=store.tenant_id, store_id=store.pk, actor_id=trial["actor"].pk, apply=True)
    assert importer.run_import(**args)["created"] == 1
    assert importer.run_import(**args)["noop"] == 1
    assert TikTokShopVideo.objects.get().source_api == "tiktok_shop_identity_partial"
    assert TikTokShopVideo.objects.get().video_type == "unknown"
    assert TikTokVideoDailyMetric.objects.count() == AffiliateOrderSnapshot.objects.count() == 0


def test_out_of_window_rows_reject_entire_artifact(trial):
    trial["set_artifact"](videos=[_video("outside-window", metric_date="2026-09-04")])
    with pytest.raises(importer.DatasetImportError, match="video_row_outside_manifest_window"):
        trial["run"](apply=True)
    assert ImportBatch.objects.count() == 0
    assert TikTokShopVideo.objects.count() == 0
    assert ExternalSourceRecord.objects.count() == 0


def test_repeated_daily_rows_collapse_by_identity_but_conflicting_identity_is_quarantined(trial):
    trial["set_artifact"](videos=[
        _video("same-id", metric_date="2026-09-01"),
        _video("same-id", metric_date="2026-09-02"),
        _video("conflict", title="Title one"),
        _video("conflict", title="Title two"),
    ])

    summary = trial["run"](apply=True)

    assert summary["eligible"] == 1
    assert summary["quarantined"] == 2
    assert TikTokShopVideo.objects.values_list("external_video_id", flat=True).get() == "same-id"


def test_manifest_tenant_store_and_component_boundaries_fail_closed(trial):
    trial["set_artifact"](videos=[_video()], tenant_id=trial["tenant"].pk + 100)
    with pytest.raises(importer.DatasetImportError, match="manifest_tenant_mismatch"):
        trial["run"](apply=True)
    assert ImportBatch.objects.count() == 0

    trial["set_artifact"](videos=[_video()], store_entries=[{
        "store_id": trial["store"].pk,
        "store_code": "wrong-store-code",
        "platform_shop_id": trial["store"].external_store_id,
        "timezone": trial["store"].timezone,
    }])
    with pytest.raises(importer.DatasetImportError, match="manifest_store_identity_mismatch"):
        trial["run"](apply=True)
    assert ImportBatch.objects.count() == 0


def test_cross_tenant_row_and_incomplete_component_set_fail_before_writes(trial):
    row = {
        "kind": "videos",
        "tenant_id": trial["tenant"].pk + 1,
        "store_id": trial["store"].pk,
        "store_code": trial["store"].code,
        "payload": _video(),
    }
    trial["set_artifact"](videos=[_video()], extra_rows=[row])
    with pytest.raises(importer.DatasetImportError, match="artifact_row_scope_mismatch"):
        trial["run"](apply=True)
    assert ImportBatch.objects.count() == 0

    trial["set_artifact"](videos=[_video()])
    trial["artifact"]["manifest"]["components"].pop()
    with pytest.raises(importer.DatasetImportError, match="manifest_component_set_incomplete"):
        trial["run"](apply=True)
    assert ImportBatch.objects.count() == 0


def test_actor_tenant_and_both_action_permissions_are_required(trial):
    foreign_tenant = Tenant.objects.create(name="Foreign tenant", code="tk-dataset-foreign")
    foreign_actor = CustomUser.objects.create_user(
        username="foreign-tk-operator",
        tenant=foreign_tenant,
        user_type=CustomUser.UserType.INTERNAL,
        password="placeholder-only",
    )
    with pytest.raises(importer.DatasetImportError, match="active_internal_actor_required"):
        trial["run"](actor_id=foreign_actor.pk)

    readonly_permission = Permission.objects.get(code="integrations.run_live_readonly")
    trial["role"].code = "revoked-dataset-admin"
    trial["role"].save(update_fields=["code"])
    with pytest.raises(importer.DatasetImportError, match="required_action_permission_missing"):
        trial["run"]()
    assert ImportBatch.objects.count() == 0


def test_store_scope_is_checked_for_both_permissions(trial):
    scope = DataScope.objects.get(tenant=trial["tenant"], role=trial["role"])
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {"store_ids": [trial["store"].pk + 10]}
    scope.save(update_fields=("scope_type", "config"))

    with pytest.raises(importer.DatasetImportError, match="influencer_store_scope_denied"):
        trial["run"]()
    assert ImportBatch.objects.count() == 0


@pytest.mark.parametrize("scope_config", [{"regions": ["US"]}, {"platform_ids": [999999]}])
def test_influencer_region_and_platform_scopes_deny_store(trial, scope_config):
    scope = DataScope.objects.get(tenant=trial["tenant"], role=trial["role"])
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = scope_config
    scope.save(update_fields=("scope_type", "config"))

    with pytest.raises(importer.DatasetImportError, match="influencer_store_scope_denied"):
        trial["run"]()
    assert ImportBatch.objects.count() == 0


def test_admin_ignores_legacy_api_scope_and_ordinary_grants_do_not_allow_import(trial):
    trial["set_artifact"](videos=[_video()])
    readonly = Permission.objects.get(code="integrations.run_live_readonly")
    trial["role"].permissions.remove(readonly)
    integration_role = Role.objects.create(
        tenant=trial["tenant"],
        code="tk-dataset-limited-integration",
        name="Limited TikTok integration scope",
    )
    integration_role.permissions.add(readonly)
    UserRole.objects.create(tenant=trial["tenant"], user=trial["actor"], role=integration_role)
    scope = DataScope.objects.create(
        tenant=trial["tenant"],
        role=integration_role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"regions": ["US"]},
    )

    assert trial["run"]()["mode"] == "dry-run"
    assert ImportBatch.objects.count() == 0

    scope.config = {"integration_config_ids": [123456]}
    scope.save(update_fields=("config",))
    assert trial["run"]()["mode"] == "dry-run"
    assert ImportBatch.objects.count() == 0

    trial["role"].code = "revoked-dataset-admin"
    trial["role"].save(update_fields=["code"])
    with pytest.raises(importer.DatasetImportError, match="required_action_permission_missing"):
        trial["run"]()
    assert ImportBatch.objects.count() == 0


def test_existing_video_from_another_source_is_never_overwritten(trial):
    existing = TikTokShopVideo.objects.create(
        tenant=trial["tenant"],
        store=trial["store"],
        external_video_id="video-1",
        title="Existing title",
        creator_id="trusted-existing-id",
        source_api="existing_source",
    )
    trial["set_artifact"](videos=[_video()])

    summary = trial["run"](apply=True)

    existing.refresh_from_db()
    assert existing.title == "Existing title"
    assert existing.creator_id == "trusted-existing-id"
    assert summary["created"] == 0
    assert summary["quarantined"] == 1
    assert summary["reasons"] == {"existing_video_untracked": 1}
    assert ExternalSourceRecord.objects.count() == 0


@pytest.mark.parametrize(("field", "value"), [("title", "Manual drift"), ("source_api", "other_source")])
def test_existing_source_record_or_video_drift_is_quarantined(trial, field, value):
    trial["set_artifact"](videos=[_video()])
    trial["run"](apply=True)
    existing = TikTokShopVideo.objects.get()
    setattr(existing, field, value)
    existing.save(update_fields=(field,))

    summary = trial["run"](apply=True)

    existing.refresh_from_db()
    assert getattr(existing, field) == value
    assert summary["created"] == 0
    assert summary["quarantined"] == 1
    assert summary["reasons"] == {"existing_source_record_conflict": 1}
    assert ExternalSourceRecord.objects.count() == 1


@pytest.mark.parametrize(
    ("field", "changed_value", "original_value"),
    [
        ("external_store_id", "shop-changed-during-run", "shop-placeholder-1"),
        ("code", "tk-ph-changed", "tk-ph-trial"),
        ("timezone", "UTC", "Asia/Manila"),
    ],
)
def test_locked_store_identity_is_revalidated_before_batch_write(
    trial, monkeypatch, field, changed_value, original_value,
):
    trial["set_artifact"](videos=[_video()])
    original_resolve = importer._resolve_scope

    def mutate_store_after_lock(tenant_id, store_id, actor_id, *, lock=False):
        resolved = original_resolve(tenant_id, store_id, actor_id, lock=lock)
        if lock:
            StoreMaster.objects.filter(pk=resolved[2].pk).update(**{field: changed_value})
            resolved[2].refresh_from_db(fields=(field,))
        return resolved

    monkeypatch.setattr(importer, "_resolve_scope", mutate_store_after_lock)

    with pytest.raises(importer.DatasetImportError, match="manifest_store_identity_mismatch"):
        trial["run"](apply=True)

    trial["store"].refresh_from_db()
    assert getattr(trial["store"], field) == original_value
    assert ImportBatch.objects.count() == 0
    assert TikTokShopVideo.objects.count() == 0


def test_command_emits_json_summary_and_rejects_oversized_limit(trial):
    trial["set_artifact"](videos=[_video()])
    from io import StringIO

    stdout = StringIO()
    call_command(
        "import_tiktok_shop_dataset",
        manifest=str(trial["manifest_path"]),
        manifest_sha256=trial["digest"],
        tenant_id=trial["tenant"].pk,
        store_id=trial["store"].pk,
        actor_id=trial["actor"].pk,
        stdout=stdout,
    )
    output = json.loads(stdout.getvalue())
    assert output["mode"] == "dry-run"
    assert output["eligible"] == 1

    with pytest.raises(CommandError, match="limit_must_be_between_1_and_20"):
        call_command(
            "import_tiktok_shop_dataset",
            manifest=str(trial["manifest_path"]),
            manifest_sha256=trial["digest"],
            tenant_id=trial["tenant"].pk,
            store_id=trial["store"].pk,
            actor_id=trial["actor"].pk,
            limit=21,
        )


def test_preview_command_never_enables_formal_import(trial, monkeypatch):
    from apps.influencers.management.commands import import_tiktok_shop_dataset as command

    def unexpected_write(**kwargs):
        pytest.fail("Preview command must reject apply before calling the importer")

    monkeypatch.setattr(command, "run_import", unexpected_write)
    with pytest.raises(CommandError, match="formal_import_disabled_use_staging"):
        call_command(
            "import_tiktok_shop_dataset", manifest=str(trial["manifest_path"]),
            manifest_sha256=trial["digest"], tenant_id=trial["tenant"].pk,
            store_id=trial["store"].pk, actor_id=trial["actor"].pk, apply=True,
        )
    assert ImportBatch.objects.count() == TikTokShopVideo.objects.count() == 0


def test_preview_command_forces_read_only_and_redacts_unexpected_errors(trial, monkeypatch):
    from apps.influencers.management.commands import import_tiktok_shop_dataset as command

    def fail_safely(**kwargs):
        assert kwargs["apply"] is False
        raise RuntimeError("private-placeholder-diagnostics")

    monkeypatch.setattr(command, "run_import", fail_safely)
    with pytest.raises(CommandError, match="^dataset_preview_failed$"):
        call_command(
            "import_tiktok_shop_dataset", manifest=str(trial["manifest_path"]),
            manifest_sha256=trial["digest"], tenant_id=trial["tenant"].pk,
            store_id=trial["store"].pk, actor_id=trial["actor"].pk,
        )
    assert ImportBatch.objects.count() == TikTokShopVideo.objects.count() == 0
