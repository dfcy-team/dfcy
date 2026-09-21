from celery import shared_task

from .services import activate_due_config_versions


@shared_task(name="configcenter.activate_due_config_versions")
def activate_due_config_versions_task():
    return activate_due_config_versions()
