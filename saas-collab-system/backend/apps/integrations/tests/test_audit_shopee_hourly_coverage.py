from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.integrations.management.commands.audit_shopee_hourly_coverage import Command


class AuditShopeeHourlyCoverageTests(SimpleTestCase):
    def test_rejects_ranges_over_seven_days_without_database_access(self):
        with self.assertRaises(CommandError):
            Command().handle(
                tenant_id=1, store_id=2,
                date_from="2026-10-01", date_to="2026-10-08",
            )

    def test_rejects_non_iso_date(self):
        with self.assertRaises(CommandError) as error:
            Command().handle(
                tenant_id=1, store_id=2,
                date_from="01-10-2026", date_to="2026-10-02",
            )
        self.assertIn("YYYY-MM-DD", str(error.exception))
