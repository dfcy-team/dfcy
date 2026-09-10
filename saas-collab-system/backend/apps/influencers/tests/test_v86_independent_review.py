"""Independent adversarial review coverage for the V86 personnel contract."""
from datetime import datetime, timezone

import pytest
from django.db.models.query import QuerySet
from rest_framework.exceptions import ValidationError

from apps.audit.models import OperationLog
from apps.influencers.models import BdSampleAttributionSnapshot, SampleFulfillment
from apps.influencers import services
from apps.influencers.tests.test_import_compatibility import (
    _source_sample,
    _user,
    sample_records,
)

pytestmark = pytest.mark.django_db


def _sample_kwargs(records, fallback, external_id):
    return dict(
        status="pending",
        source_row={"id": external_id, "status": "pending", "owner": "  历史人员  "},
        user=records["user"],
        tenant=records["tenant"],
        source=services.FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        request_key=f"review:{external_id}",
        request_hash="e" * 64,
        validated_data={
            "fulfillment_no": external_id,
            "influencer": records["influencer"],
            "store": records["store"],
            "owner": fallback,
            "link_type": "direct",
        },
        item_payloads=[],
        sample_sent_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        source_owner_name_snapshot="  历史人员  ",
        owner_resolution="unmatched_fallback",
        personnel_policy=services.FEISHU_PERSONNEL_POLICY,
        return_metadata=True,
    )


def test_review_existing_owner_switch_preserves_frozen_attribution_and_replay(sample_records):
    records = sample_records
    fallback = _user(records["tenant"], "liyejun")
    existing = _source_sample(records, "review-existing-owner")
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=existing.pk),
        external_id="REVIEW-EXISTING-OWNER",
        fulfillment_no="REVIEW-EXISTING-OWNER",
    )
    frozen_before = BdSampleAttributionSnapshot.objects.filter(fulfillment=existing).values().get()
    kwargs = _sample_kwargs(records, fallback, "REVIEW-EXISTING-OWNER")
    first = services.import_sample_fulfillment_snapshot(**kwargs)
    existing.refresh_from_db()
    assert first["outcome"] == "updated"
    assert existing.owner_id == fallback.pk
    assert existing.source_owner_name_snapshot == "  历史人员  "
    assert BdSampleAttributionSnapshot.objects.filter(fulfillment=existing).values().get() == frozen_before
    unchanged = (existing.version, existing.updated_at, OperationLog.objects.count())
    second = services.import_sample_fulfillment_snapshot(**kwargs)
    existing.refresh_from_db()
    assert second["outcome"] == "noop"
    assert (existing.version, existing.updated_at, OperationLog.objects.count()) == unchanged
    assert BdSampleAttributionSnapshot.objects.filter(fulfillment=existing).values().get() == frozen_before


def test_review_new_sample_audits_actual_owner_source_and_policy(sample_records):
    records = sample_records
    fallback = _user(records["tenant"], "liyejun")
    result = services.import_sample_fulfillment_snapshot(**_sample_kwargs(records, fallback, "REVIEW-NEW-OWNER"))
    row = result["fulfillment"]
    evidence = [
        log.after_data
        for log in OperationLog.objects.filter(
            tenant=records["tenant"], object_type="sample_fulfillment", object_id=str(row.pk)
        )
    ]
    assert any(
        data.get("actual_owner_id") == fallback.pk
        and data.get("source_owner_name_snapshot") == "  历史人员  "
        and data.get("owner_resolution") == "unmatched_fallback"
        and data.get("personnel_policy") == services.FEISHU_PERSONNEL_POLICY
        and data.get("owner_reason")
        for data in evidence
    )


def test_review_match_normalization_preserves_nfkc_casefold_equivalence(sample_records):
    records = sample_records
    user = records["user"]
    user.full_name = "Straße ＯＷＮＥＲ"
    user.save(update_fields=["full_name"])
    assert list(services._qualified_personnel_matches(user, "  STRASSE owner ").values_list("pk", flat=True)) == [user.pk]


def test_review_blank_dispatcher_preserves_raw_whitespace_and_binds_owner(sample_records):
    records = sample_records
    personnel = services._normalise_personnel_mapping(
        None,
        owner_name=records["user"].username,
        dispatcher_name=" \u3000 ",
        owner_resolution="exact_match",
        dispatcher_resolution="blank_dispatcher_uses_owner",
        personnel_policy=services.FEISHU_PERSONNEL_POLICY,
        roles=("owner", "dispatcher"),
    )
    assert personnel["dispatcher"]["name"] == " \u3000 "
    services._validate_personnel_role(
        user=records["user"], role="dispatcher", entry=personnel["dispatcher"],
        actual_user=records["user"], owner_user=records["user"], owner_entry=personnel["owner"],
    )
    with pytest.raises(ValidationError):
        services._validate_personnel_role(
            user=records["user"], role="dispatcher", entry=personnel["dispatcher"],
            actual_user=records["executor"], owner_user=records["user"], owner_entry=personnel["owner"],
        )
    with pytest.raises(ValidationError):
        services._validate_personnel_role(
            user=records["user"], role="dispatcher", entry={**personnel["dispatcher"], "name": "not blank"},
            actual_user=records["user"], owner_user=records["user"], owner_entry=personnel["owner"],
        )


def test_review_fallback_cannot_be_unicode_lookalike_account(sample_records):
    records = sample_records
    lookalike = _user(records["tenant"], "ｌｉｙｅｊｕｎ")
    with pytest.raises(ValidationError):
        services._validate_personnel_role(
            user=records["user"], role="owner",
            entry={"name": "historical missing", "resolution": "unmatched_fallback", "actual_id": lookalike.pk},
            actual_user=lookalike,
        )


@pytest.mark.parametrize("name", [123, ["person"], "x" * 256])
def test_review_personnel_rejects_nonstring_or_overlength_evidence(name):
    with pytest.raises(ValidationError):
        services._normalise_personnel_mapping(
            None, owner_name=name, owner_resolution="unmatched_fallback",
            personnel_policy=services.FEISHU_PERSONNEL_POLICY,
        )
