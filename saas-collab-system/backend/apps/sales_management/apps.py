from django.apps import AppConfig


class SalesManagementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales_management"
    verbose_name = "Sales management"

    def ready(self):
        from . import warehouse_order_signals  # noqa: F401
