from django.conf import settings


def test_overdue_sample_fulfillment_task_runs_daily_without_arguments():
    schedule = settings.CELERY_BEAT_SCHEDULE["mark-overdue-sample-fulfillments"]

    assert schedule["task"] == "influencers.mark_overdue_sample_fulfillments"
    assert schedule["args"] == ()
    assert schedule["schedule"].minute == {0}
    assert schedule["schedule"].hour == {18}
