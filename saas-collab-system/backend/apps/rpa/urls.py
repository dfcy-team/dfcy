from django.urls import path

from .views import append_task_log, claim_task, complete_task, fail_task, health, task_heartbeat


urlpatterns = [
    path("health/", health, name="rpa-health"),
    path("tasks/claim/", claim_task, name="rpa-task-claim"),
    path("tasks/<int:task_id>/heartbeat/", task_heartbeat, name="rpa-task-heartbeat"),
    path("tasks/<int:task_id>/logs/", append_task_log, name="rpa-task-logs"),
    path("tasks/<int:task_id>/complete/", complete_task, name="rpa-task-complete"),
    path("tasks/<int:task_id>/fail/", fail_task, name="rpa-task-fail"),
]
