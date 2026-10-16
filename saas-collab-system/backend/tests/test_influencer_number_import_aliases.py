from datetime import datetime, timezone

import pytest
from rest_framework.exceptions import ValidationError

from apps.influencers.models import OutreachTask, SampleFulfillment
from apps.influencers.services import (
    FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    import_outreach_task_snapshot, import_sample_fulfillment_snapshot,
    update_outreach_task, update_sample_fulfillment,
)
from apps.influencers.tests.test_import_compatibility import sample_records, _personnel_kwargs


pytestmark = pytest.mark.django_db


def sample_arguments(r):
    return dict(
        status="pending", event={"source": "example", "id": "EXAMPLE-SOURCE-SAMPLE", "status": "pending"},
        user=r["user"], tenant=r["tenant"], source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={"external_id": "EXAMPLE-SOURCE-SAMPLE"},
        validated_data={"fulfillment_no": "YPDD10646", "influencer": r["influencer"],
                        "store": r["store"], "owner": r["user"], "link_type": "direct"},
        item_payloads=[], sample_sent_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        actor=r["user"], **_personnel_kwargs(r["user"]),
    )


def test_incremental_sample_replay_after_manual_rename_keeps_the_same_record(sample_records):
    r = sample_records
    arguments = sample_arguments(r)
    sample, created = import_sample_fulfillment_snapshot(**arguments)
    assert created
    sample = update_sample_fulfillment(user=r["user"], fulfillment=sample,
        expected_version=sample.version, validated_data={"fulfillment_no": "YPDD10647"})
    before = SampleFulfillment.objects.values().get(pk=sample.pk)
    replayed, created = import_sample_fulfillment_snapshot(**arguments)
    assert not created and replayed.pk == sample.pk and replayed.fulfillment_no == "YPDD10647"
    assert SampleFulfillment.objects.values().get(pk=sample.pk) == before
    assert SampleFulfillment.objects.count() == 1


def test_another_source_row_cannot_claim_a_renamed_samples_old_number(sample_records):
    r = sample_records
    arguments = sample_arguments(r)
    sample, _ = import_sample_fulfillment_snapshot(**arguments)
    update_sample_fulfillment(user=r["user"], fulfillment=sample,
        expected_version=sample.version, validated_data={"fulfillment_no": "YPDD10647"})
    arguments["event"] = {"id": "ANOTHER-EXAMPLE-SAMPLE", "status": "pending"}
    arguments["source_row"] = {"external_id": "ANOTHER-EXAMPLE-SAMPLE"}
    with pytest.raises(ValidationError, match="reserved"):
        import_sample_fulfillment_snapshot(**arguments)
    assert SampleFulfillment.objects.count() == 1


def test_incremental_task_replay_after_manual_rename_preserves_user_number(sample_records):
    r = sample_records
    arguments = dict(
        status="pending", event={"external_id": "EXAMPLE-SOURCE-TASK"},
        user=r["user"], tenant=r["tenant"], source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        source_row={"external_id": "EXAMPLE-SOURCE-TASK", "dispatch_time": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        validated_data={"task_no": "DRJL0279", "store": r["store"], "owner": r["user"],
                        "dispatcher": r["executor"], "external_product_id": "EXAMPLE-PRODUCT"},
        actor=r["user"], **_personnel_kwargs(r["user"], r["executor"]),
    )
    task, created = import_outreach_task_snapshot(**arguments)
    assert created
    task = update_outreach_task(user=r["user"], task=task, expected_version=task.version,
                                validated_data={"task_no": "DRJL0280"})
    before = OutreachTask.objects.values().get(pk=task.pk)
    replayed, created = import_outreach_task_snapshot(**arguments)
    assert not created and replayed.pk == task.pk and replayed.task_no == "DRJL0280"
    assert OutreachTask.objects.values().get(pk=task.pk) == before
