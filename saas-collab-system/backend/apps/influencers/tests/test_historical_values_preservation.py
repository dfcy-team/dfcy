from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError

from apps.audit.models import OperationLog
from apps.influencers.models import (
    BdSampleAttributionSnapshot,
    FulfillmentStatusEvent,
    Influencer,
    InfluencerProfile,
    InfluencerRestriction,
    SampleFulfillment,
    SampleItem,
)
from apps.influencers import services
from apps.influencers.services import (
    FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    create_sample_fulfillment,
    import_sample_fulfillment_snapshot,
)
from apps.influencers.tests.test_import_compatibility import _personnel_kwargs, sample_records
from apps.tenants.models import Tenant
from apps.permissions.models import UserRole


pytestmark = pytest.mark.django_db

TZ8 = dt_timezone(timedelta(hours=8))
SENT = datetime(2026, 9, 8, 10, 30, tzinfo=TZ8)
SHIPPED = datetime(2026, 9, 9, 15, 45, tzinfo=TZ8)
DEADLINE = datetime(2026, 9, 20, 23, 59, tzinfo=TZ8)


def _call(records, *, status="shipped", source_row=None, item=None, **changes):
    maintenance = changes.pop("maintenance", True)
    if records["user"].is_superuser != maintenance:
        records["user"].is_superuser = maintenance
        records["user"].save(update_fields=["is_superuser"])
    facts = {
        "source": FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "id": "HIST-SAMPLE-001",
        "status": status,
        "video_deadline_at": DEADLINE.isoformat(),
    }
    facts.update(source_row or {})
    kwargs = {
        "status": status,
        "source_row": facts,
        "user": records["user"],
        "tenant": records["tenant"],
        "actor": records["user"],
        "validated_data": {
            "fulfillment_no": "HIST-SAMPLE-001",
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": records["user"],
            "link_type": "direct",
            "external_product_id": "SYNTHETIC-PRODUCT",
            "product_name_snapshot": "Synthetic historical sample",
        },
        "item_payloads": [item or {
            "site_code": "PH", "requested_sku": "HIST-SKU-1",
            "product_name": "Synthetic item", "quantity": 1,
            "unit_cost": None, "cost_amount": None, "currency": "",
        }],
        "sample_sent_at": SENT,
        "shipped_at": SHIPPED if status in ("shipped", "published") else None,
        "preserve_historical_values": True,
        "return_metadata": True,
        **_personnel_kwargs(records["user"]),
    }
    kwargs.update(changes)
    return import_sample_fulfillment_snapshot(**kwargs)


def _inactive_batch_creator(records):
    creator = records["influencer"]
    creator.status = Influencer.Status.INACTIVE
    creator.code = "handoff-20261009-" + "a" * 24
    creator.handle = "inactive.history.creator"
    creator.save(update_fields=["status", "code", "handle"])
    return creator


def _historical_inactive_call(records, **changes):
    changes.setdefault("historical_inactive_manifest_sha256", services.HISTORICAL_INACTIVE_SAMPLE_MANIFEST)
    return _call(records, **changes)


def _counts(records):
    return (
        SampleFulfillment.objects.filter(tenant=records["tenant"]).count(),
        SampleItem.objects.filter(tenant=records["tenant"]).count(),
        FulfillmentStatusEvent.objects.filter(tenant=records["tenant"]).count(),
        BdSampleAttributionSnapshot.objects.filter(tenant=records["tenant"]).count(),
        OperationLog.objects.filter(tenant=records["tenant"]).count(),
    )


@pytest.mark.parametrize("status", ["published", "shipped"])
def test_preserves_null_historical_values_and_blank_currency(sample_records, status):
    r = sample_records
    result = _call(r, status=status, source_row={"video_deadline_at": None},
                   shipped_at=None,
                   item={"site_code": "PH", "requested_sku": "HIST-SKU-NULL",
                         "product_name": "Synthetic", "quantity": 1,
                         "unit_cost": None, "cost_amount": None, "currency": ""})
    f = result["fulfillment"]
    item = f.items.get()
    assert result["outcome"] == "created"
    assert f.video_deadline_at is None
    assert f.shipped_at is None
    assert item.unit_cost is None and item.cost_amount is None
    assert item.currency == ""
    assert f.status == status
    assert f.sample_sent_at == SENT.astimezone(dt_timezone.utc)


def test_explicit_deadline_retained_and_legacy_default_keeps_computed_deadline(sample_records):
    r = sample_records
    historical = _call(r)
    assert historical["fulfillment"].video_deadline_at == DEADLINE.astimezone(dt_timezone.utc)

    # The ordinary mode still computes its deadline from source shipment date.
    from apps.influencers.tests.test_import_compatibility import FEISHU_PERSONNEL_POLICY
    user = r["executor"]
    row = {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "id": "LEGACY-COMPAT-1", "status": "shipped"}
    legacy = import_sample_fulfillment_snapshot(
        "shipped", user=user, tenant=r["tenant"], actor=user,
        source_row=row,
        validated_data={"fulfillment_no": "LEGACY-COMPAT-1", "influencer": r["influencer"],
                        "store": r["store"], "owner": r["user"], "link_type": "direct"},
        item_payloads=[], sample_sent_at=SENT, shipped_at=SHIPPED,
        source_owner_name_snapshot=r["user"].username, owner_resolution="exact_match",
        personnel_policy=FEISHU_PERSONNEL_POLICY, return_metadata=True,
    )
    assert legacy["created"] is True
    legacy = legacy["fulfillment"]
    assert legacy.video_deadline_at == SHIPPED.astimezone(dt_timezone.utc) + timedelta(days=20)
    assert legacy.items.count() == 0


@pytest.mark.parametrize("status,deadline", [("published", None), ("shipped", DEADLINE)])
def test_source_dates_and_monetary_facts_are_preserved(sample_records, status, deadline):
    r = sample_records
    item = {"site_code": "PH", "requested_sku": f"FACT-{status}", "quantity": 2,
            "unit_cost": Decimal("3.2500"), "cost_amount": Decimal("6.5000"), "currency": "CNY"}
    result = _call(r, status=status, source_row={"video_deadline_at": deadline.isoformat() if deadline else None}, item=item)
    f = result["fulfillment"]
    assert f.video_deadline_at == (deadline.astimezone(dt_timezone.utc) if deadline else None)
    assert f.shipped_at == SHIPPED.astimezone(dt_timezone.utc)
    saved = f.items.get()
    assert (saved.unit_cost, saved.cost_amount, saved.currency) == (Decimal("3.2500"), Decimal("6.5000"), "CNY")


@pytest.mark.parametrize("mutate", [
    lambda kw: kw["source_row"].pop("video_deadline_at"),
    lambda kw: kw["source_row"].update(video_deadline_at="not-a-date"),
    lambda kw: kw["source_row"].update(source="other_source"),
    lambda kw: kw.update(status="unknown"),
    lambda kw: kw.update(preserve_historical_values=1),
    lambda kw: kw.update(preserve_historical_values="true"),
])
def test_rejects_malformed_or_incomplete_source_facts(sample_records, mutate):
    r = sample_records
    # Construct the valid call without executing it so each mutation has a clean transaction.
    facts = {"source": FEISHU_FULL_SAMPLE_STATUS_SOURCE, "id": "INVALID-ROW", "status": "shipped",
             "video_deadline_at": DEADLINE.isoformat()}
    kw = {"status": "shipped", "source_row": facts, "user": r["user"], "tenant": r["tenant"],
          "actor": r["user"], "validated_data": {"fulfillment_no": "INVALID-ROW", "influencer": r["influencer"],
          "store": r["store"], "owner": r["user"], "link_type": "direct"}, "item_payloads": [],
          "sample_sent_at": SENT, "shipped_at": SHIPPED, "preserve_historical_values": True,
          **_personnel_kwargs(r["user"])}
    r["user"].is_superuser = True
    r["user"].save(update_fields=["is_superuser"])
    mutate(kw)
    with pytest.raises(ValidationError):
        import_sample_fulfillment_snapshot(**kw)


@pytest.mark.parametrize("currency,amount", [(None, None), ("USD", None), ("", Decimal("2.00"))])
def test_rejects_missing_invalid_or_monetized_blank_currency(sample_records, currency, amount):
    r = sample_records
    item = {"site_code": "PH", "requested_sku": "BAD-CURRENCY", "quantity": 1,
            "unit_cost": None, "cost_amount": amount}
    if currency is not None:
        item["currency"] = currency
    with pytest.raises(ValidationError):
        _call(r, item=item)


def test_requires_maintenance_admin_and_qualified_bd_owner(sample_records):
    r = sample_records
    with pytest.raises(ValidationError, match="maintenance administrator"):
        _call(r, maintenance=False)
    # A name with no uniquely qualified BD owner cannot be certified as exact.
    user = r["user"]
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    with pytest.raises(ValidationError):
        _call(r, source_owner_name_snapshot="no-such-source-person", owner_resolution="exact_match")


def test_rejects_foreign_tenant_and_invalid_call_modes(sample_records):
    r = sample_records
    with pytest.raises(ValidationError):
        _call(r, tenant=Tenant.objects.get(pk=r["other_user"].tenant_id))
    with pytest.raises(ValidationError):
        import_sample_fulfillment_snapshot("shipped", user=r["user"], preserve_historical_values=True)
    with pytest.raises(ValidationError):
        _call(r, source_row={"source": "not_feishu"})


def test_exact_replay_has_no_write_sql_and_changed_facts_conflict(sample_records):
    r = sample_records
    first = _call(r)
    with CaptureQueriesContext(connection) as captured:
        replay = _call(r)
    writes = [q["sql"] for q in captured.captured_queries
              if q["sql"].lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
    assert replay["outcome"] == "noop"
    assert writes == []
    for change in (
        {"source_row": {"video_deadline_at": None}},
        {"item": {"site_code": "PH", "requested_sku": "CHANGED-ITEM", "quantity": 1, "currency": ""}},
        {"validated_data": {"fulfillment_no": "HIST-SAMPLE-001", "influencer": r["second_influencer"],
          "store": r["store"], "owner": r["user"], "link_type": "direct"}},
        {"request_hash": "f" * 64},
    ):
        with pytest.raises(ValidationError):
            _call(r, **change)
    assert first["fulfillment"].items.count() == 1


def test_existing_fulfillment_is_not_overwritten_or_restored(sample_records):
    r = sample_records
    created = _call(r)["fulfillment"]
    QuerySet.update(SampleFulfillment.objects.filter(pk=created.pk), is_deleted=True, deleted_at=SENT)
    created.refresh_from_db()
    before = (created.request_hash, created.status, created.video_deadline_at, created.is_deleted)
    replay = _call(r)
    created.refresh_from_db()
    assert replay["outcome"] == "noop"
    assert (created.request_hash, created.status, created.video_deadline_at, created.is_deleted) == before


@pytest.mark.parametrize("failure", ["snapshot", "audit"])
def test_snapshot_or_audit_failure_rolls_back_every_row(sample_records, failure):
    r = sample_records
    before = _counts(r)
    if failure == "snapshot":
        # Let normal manager operations work until the post-create snapshot lookup.
        with patch.object(BdSampleAttributionSnapshot.objects, "select_for_update", side_effect=RuntimeError("snapshot fault")):
            with pytest.raises(RuntimeError):
                _call(r)
    else:
        from apps.influencers import services
        original = services._audit
        def fail_historical(user, action, *args, **kwargs):
            if action == "feishu_import_historical_values":
                raise RuntimeError("audit fault")
            return original(user, action, *args, **kwargs)
        with patch("apps.influencers.services._audit", side_effect=fail_historical):
            with pytest.raises(RuntimeError):
                _call(r)
    assert _counts(r) == before


@pytest.mark.parametrize("link_type", ["direct", "task"])
def test_20261009_inactive_creator_can_be_linked_without_profile_or_status_changes(sample_records, link_type):
    r = sample_records
    creator = _inactive_batch_creator(r)
    profile = InfluencerProfile.objects.create(
        tenant=r["tenant"], influencer=creator, display_name="Historical profile",
        market="PH", profile_notes="Keep unchanged",
    )
    before_creator = {f.attname: getattr(creator, f.attname) for f in creator._meta.concrete_fields}
    before_profile = {f.attname: getattr(profile, f.attname) for f in profile._meta.concrete_fields}
    validated = {"fulfillment_no": "INACTIVE-HISTORY-" + link_type,
                 "influencer": creator, "store": r["store"], "owner": r["user"],
                 "link_type": "direct", "external_product_id": "SYNTHETIC-PRODUCT",
                 "product_name_snapshot": "Synthetic historical sample"}
    if link_type == "task":
        validated.update(link_type="DRJL", outreach_task=r["task"],
                         external_product_id=r["task"].external_product_id)
    result = _historical_inactive_call(r, validated_data=validated)
    assert result["outcome"] == "created"
    creator.refresh_from_db()
    profile.refresh_from_db()
    assert {f.attname: getattr(creator, f.attname) for f in creator._meta.concrete_fields} == before_creator
    assert {f.attname: getattr(profile, f.attname) for f in profile._meta.concrete_fields} == before_profile


@pytest.mark.parametrize("changes", [
    {"historical_inactive_manifest_sha256": None},
    {"historical_inactive_manifest_sha256": "0" * 64},
    {"preserve_historical_values": False},
    {"maintenance": False},
])
def test_inactive_batch_requires_manifest_historical_mode_and_maintenance_actor(sample_records, changes):
    r = sample_records
    _inactive_batch_creator(r)
    with pytest.raises(ValidationError):
        _historical_inactive_call(r, **changes)


@pytest.mark.parametrize("code", ["old-inactive-code", "handoff-20261009-" + "A" * 24,
                                   "handoff-20261009-" + "a" * 23])
def test_historical_manifest_does_not_allow_nonbatch_inactive_creator(sample_records, code):
    r = sample_records
    creator = r["influencer"]
    creator.status = Influencer.Status.INACTIVE
    creator.code = code
    creator.save(update_fields=["status", "code"])
    with pytest.raises(ValidationError):
        _historical_inactive_call(r)


def test_inactive_identity_blacklist_still_blocks_historical_link(sample_records):
    r = sample_records
    creator = _inactive_batch_creator(r)
    duplicate = r["second_influencer"]
    duplicate.handle = creator.handle
    duplicate.save(update_fields=["handle"])
    InfluencerRestriction.objects.create(
        tenant=r["tenant"], influencer=duplicate, created_by=r["user"],
        is_blacklisted=True, reason="Synthetic identity restriction",
    )
    with pytest.raises(ValidationError):
        _historical_inactive_call(r)


@pytest.mark.parametrize("case", ["foreign_tenant", "cancelled_task", "product_mismatch", "invalid_bd"])
def test_inactive_historical_link_keeps_tenant_task_product_and_bd_validation(sample_records, case):
    r = sample_records
    creator = _inactive_batch_creator(r)
    changes = {}
    validated = {"fulfillment_no": "INACTIVE-INVALID-" + case, "influencer": creator,
                 "store": r["store"], "owner": r["user"], "link_type": "direct",
                 "external_product_id": "SYNTHETIC-PRODUCT"}
    if case == "foreign_tenant":
        changes["tenant"] = Tenant.objects.get(pk=r["other_user"].tenant_id)
    elif case == "cancelled_task":
        from apps.influencers.services import transition_outreach_task
        transition_outreach_task(user=r["user"], task=r["task"], status="cancelled", expected_version=r["task"].version)
        validated.update(link_type="DRJL", outreach_task=r["task"])
    elif case == "product_mismatch":
        validated.update(link_type="DRJL", outreach_task=r["task"], external_product_id="WRONG-PRODUCT")
    else:
        changes.update(source_owner_name_snapshot="missing-synthetic-bd", owner_resolution="exact_match")
    with pytest.raises(ValidationError):
        _historical_inactive_call(r, validated_data=validated, **changes)


def test_inactive_historical_exact_replay_is_read_only(sample_records):
    r = sample_records
    _inactive_batch_creator(r)
    first = _historical_inactive_call(r)
    with CaptureQueriesContext(connection) as captured:
        replay = _historical_inactive_call(r)
    writes = [q["sql"] for q in captured.captured_queries
              if q["sql"].lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
    assert first["outcome"] == "created" and replay["outcome"] == "noop"
    assert writes == []


@pytest.mark.parametrize("failure", ["snapshot", "audit"])
def test_inactive_historical_failure_rolls_back_without_activating_creator(sample_records, failure):
    r = sample_records
    creator = _inactive_batch_creator(r)
    before = _counts(r)
    if failure == "snapshot":
        with patch.object(BdSampleAttributionSnapshot.objects, "select_for_update", side_effect=RuntimeError("snapshot fault")):
            with pytest.raises(RuntimeError):
                _historical_inactive_call(r)
    else:
        original = services._audit
        def fail_historical(user, action, *args, **kwargs):
            if action == "feishu_import_historical_values":
                raise RuntimeError("audit fault")
            return original(user, action, *args, **kwargs)
        with patch("apps.influencers.services._audit", side_effect=fail_historical):
            with pytest.raises(RuntimeError):
                _historical_inactive_call(r)
    creator.refresh_from_db()
    assert creator.status == Influencer.Status.INACTIVE
    assert _counts(r) == before


@pytest.mark.parametrize("deleted", [False, True])
def test_inactive_historical_import_cannot_adopt_manual_or_deleted_business_number(sample_records, deleted):
    r = sample_records
    creator = r["influencer"]
    manual, _ = create_sample_fulfillment(
        user=r["user"], request_key="manual-number-conflict",
        validated_data={"fulfillment_no": "HIST-SAMPLE-001", "influencer": creator,
                        "store": r["store"], "owner": r["user"], "link_type": "direct"},
        item_payloads=[],
    )
    if deleted:
        QuerySet.update(SampleFulfillment.objects.filter(pk=manual.pk), is_deleted=True, deleted_at=SENT)
    manual.refresh_from_db()
    before = (manual.source, manual.external_id, manual.request_key, manual.request_hash, manual.is_deleted)
    _inactive_batch_creator(r)
    with pytest.raises(ValidationError):
        _historical_inactive_call(r)
    manual.refresh_from_db()
    assert (manual.source, manual.external_id, manual.request_key, manual.request_hash, manual.is_deleted) == before


def test_explicit_null_currency_is_rejected_for_inactive_batch(sample_records):
    r = sample_records
    _inactive_batch_creator(r)
    with pytest.raises(ValidationError):
        _historical_inactive_call(r, item={"site_code": "PH", "requested_sku": "NULL-CURRENCY",
                                           "quantity": 1, "unit_cost": None,
                                           "cost_amount": None, "currency": None})


def test_ordinary_sample_creation_still_rejects_inactive_creator(sample_records):
    r = sample_records
    creator = _inactive_batch_creator(r)
    data = {"fulfillment_no": "ORDINARY-INACTIVE", "influencer": creator,
            "store": r["store"], "owner": r["user"], "link_type": "direct"}
    with pytest.raises(ValidationError):
        create_sample_fulfillment(user=r["user"], request_key="ordinary-inactive",
                                  validated_data=data, item_payloads=[])
    with pytest.raises(ValidationError):
        _call(r, preserve_historical_values=False)


@pytest.mark.parametrize("mutation", ["blacklist", "cancelled_task", "deleted_task", "changed_relation", "bd_revoked"])
def test_historical_replay_rechecks_current_constraints_without_reconciling_rows(sample_records, mutation):
    r = sample_records
    creator = _inactive_batch_creator(r)
    data = {"fulfillment_no": "REPLAY-CURRENT-GATES", "influencer": creator,
            "store": r["store"], "owner": r["user"], "link_type": "DRJL",
            "outreach_task": r["task"], "external_product_id": r["task"].external_product_id}
    first = _historical_inactive_call(r, validated_data=data)["fulfillment"]
    if mutation == "blacklist":
        duplicate = r["second_influencer"]
        duplicate.handle = creator.handle
        duplicate.save(update_fields=["handle"])
        InfluencerRestriction.objects.create(
            tenant=r["tenant"], influencer=duplicate, created_by=r["user"],
            is_blacklisted=True, reason="Synthetic later restriction",
        )
    elif mutation == "cancelled_task":
        QuerySet.update(type(r["task"]).objects.filter(pk=r["task"].pk), status="cancelled")
    elif mutation == "deleted_task":
        QuerySet.update(type(r["task"]).objects.filter(pk=r["task"].pk), is_deleted=True,
                        deleted_at=SENT)
    elif mutation == "changed_relation":
        QuerySet.update(SampleFulfillment.objects.filter(pk=first.pk), store_id=r["second_store"].pk)
    else:
        UserRole.objects.filter(tenant=r["tenant"], user=r["user"], role__code="bd").delete()
    first.refresh_from_db()
    before = {field.attname: getattr(first, field.attname) for field in first._meta.concrete_fields}
    before_counts = _counts(r)
    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(ValidationError):
            _historical_inactive_call(r, validated_data=data)
    writes = [q["sql"] for q in captured.captured_queries
              if q["sql"].lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
    assert writes == []
    first.refresh_from_db()
    assert {field.attname: getattr(first, field.attname) for field in first._meta.concrete_fields} == before
    assert _counts(r) == before_counts
    creator.refresh_from_db()
    assert creator.status == Influencer.Status.INACTIVE


def test_inactive_batch_history_scope_is_audited(sample_records):
    r = sample_records
    _inactive_batch_creator(r)
    _historical_inactive_call(r)
    audit = OperationLog.objects.get(tenant=r["tenant"], action="feishu_import_historical_values")
    assert audit.after_data["historical_inactive_manifest_sha256"] == services.HISTORICAL_INACTIVE_SAMPLE_MANIFEST
    assert audit.after_data["linked_inactive_creator"] is True
    assert audit.after_data["create_only"] is True
