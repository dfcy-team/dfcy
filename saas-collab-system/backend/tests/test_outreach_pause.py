import pytest
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.influencers.models import OutreachTask, SampleFulfillment, Influencer
from apps.influencers.services import (
    _assert_task_accepts_target, recompute_outreach_task_completion, transition_outreach_task,
)
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import store_for, user_with_permissions

pytestmark = pytest.mark.django_db


def setup_task():
    tenant = Tenant.objects.create(name="Pause test", code="pause-test")
    user, client = user_with_permissions(tenant, "pause-user", "influencers.outreach.view", "influencers.outreach.manage")
    task = OutreachTask.objects.create(tenant=tenant, task_no="PAUSE-1", store=store_for(tenant, "pause"),
                                      dispatcher=user, owner=user, target_count=1)
    QuerySet.update(OutreachTask.objects.filter(pk=task.pk), status="in_progress", started_at=timezone.now())
    task.refresh_from_db()
    return user, client, task


def test_pause_resume_preserves_timestamps_and_existing_samples():
    user, client, task = setup_task()
    creator = Influencer.objects.create(tenant=user.tenant, code="pause-creator", name="Creator", platform="TikTok", handle="pause.creator")
    sample = SampleFulfillment.objects.create(tenant=user.tenant, fulfillment_no="PAUSE-SAMPLE", request_key="pause-key",
        request_hash="pause-hash", store=task.store, influencer=creator, owner=user, outreach_task=task, calculated_cost="12.34")
    start = task.started_at
    for version, status in [(1, "paused"), (2, "in_progress")]:
        response = client.post(f"/api/internal/influencers/outreach-tasks/{task.pk}/status/", {"status":status},
                               format="json", HTTP_IF_MATCH=f'"{version}"')
        assert response.status_code == 200, response.data
        assert response.data["data"]["status"] == status
        task.refresh_from_db()
        assert task.started_at == start and task.finalized_at is None
    sample.refresh_from_db()
    assert str(sample.calculated_cost) == "12.3400" and sample.status == "pending"


def test_paused_task_cannot_receive_samples_or_auto_complete():
    user, _, task = setup_task()
    task = transition_outreach_task(user=user, task=task, status="paused", expected_version=1)
    for completed in (False, True):
        with pytest.raises(ValidationError):
            _assert_task_accepts_target(task, allow_completed=completed)
    recompute_outreach_task_completion(user=user, task=task)
    task.refresh_from_db()
    assert task.status == "paused"


@pytest.mark.parametrize("status", ["completed", "cancelled", "pending"])
def test_pause_rejects_invalid_source_status(status):
    user, _, task = setup_task()
    QuerySet.update(OutreachTask.objects.filter(pk=task.pk), status=status)
    with pytest.raises(ValidationError):
        transition_outreach_task(user=user, task=task, status="paused", expected_version=1)


def test_pause_stale_version_and_permissions_fail_closed():
    user, client, task = setup_task()
    transition_outreach_task(user=user, task=task, status="paused", expected_version=1)
    response = client.post(f"/api/internal/influencers/outreach-tasks/{task.pk}/status/", {"status":"in_progress"},
                           format="json", HTTP_IF_MATCH='"1"')
    assert response.status_code == 409
    _, read_only = user_with_permissions(user.tenant, "pause-viewer", "influencers.outreach.view")
    response = read_only.post(f"/api/internal/influencers/outreach-tasks/{task.pk}/status/", {"status":"in_progress"},
                              format="json", HTTP_IF_MATCH='"2"')
    assert response.status_code == 403
