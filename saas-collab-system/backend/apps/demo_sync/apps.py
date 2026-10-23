from django.apps import AppConfig


class DemoSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo_sync"
    verbose_name = "开发环境数据同步"
