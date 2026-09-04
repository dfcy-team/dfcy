from django.conf import settings


def test_overdue_sample_fulfillment_task_runs_daily_without_arguments():
    schedule = settings.CELERY_BEAT_SCHEDULE["mark-overdue-sample-fulfillments"]

    assert schedule == {
        "task": "influencers.mark_overdue_sample_fulfillments",
        "schedule": 86400.0,
        "args": (),
    }
