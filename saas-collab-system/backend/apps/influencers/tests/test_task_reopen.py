import pytest
from rest_framework.exceptions import ValidationError

from apps.influencers.services import update_outreach_task, transition_outreach_task
from apps.influencers.tests.test_import_compatibility import sample_records

pytestmark = pytest.mark.django_db


def test_reopen_completed_task_clears_completion_preserves_facts(sample_records):
    task = sample_records['task']
    task = transition_outreach_task(user=sample_records['user'], task=task,
        status='in_progress', expected_version=task.version)
    task = transition_outreach_task(user=sample_records['user'], task=task,
        status='completed', expected_version=task.version)
    now = task.started_at
    old_version = task.version
    result = update_outreach_task(user=sample_records['user'], task=task,
        validated_data={'status': 'in_progress'}, expected_version=old_version)
    assert result.status == 'in_progress'
    assert result.finalized_at is None
    assert result.started_at == now
    assert result.task_no == task.task_no
    assert result.version == old_version + 1
    with pytest.raises(ValidationError):
        update_outreach_task(user=sample_records['user'], task=result,
            validated_data={'status': 'completed'}, expected_version=old_version)


def test_cancelled_task_cannot_reopen(sample_records):
    task = sample_records['task']
    task = transition_outreach_task(user=sample_records['user'], task=task,
        status='cancelled', expected_version=task.version)
    with pytest.raises(ValidationError):
        update_outreach_task(user=sample_records['user'], task=task,
            validated_data={'status': 'in_progress'}, expected_version=task.version)
