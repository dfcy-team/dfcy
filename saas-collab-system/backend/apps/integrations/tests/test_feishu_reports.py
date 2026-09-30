import csv
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.feishu_reports import METRICS, build_report, report_csv, _window


def result(dataset, rows):
    filters = {"date_from": "2026-01-01", "date_to": "2026-01-01"}
    return {"rows": rows, "config": {"filters": filters}, "truncated": False, "refreshed_at": None}


class FeishuReportsTests(SimpleTestCase):
    @patch("apps.integrations.feishu_reports.query_dataset")
    def test_sales_uses_recipient_query_and_keeps_currency_separate(self, query):
        query.return_value = result("sales", [
            {"currency": "USD", "order_count": 2, "valid_order_count": 2, "gross_sales": "8.50"},
            {"currency": "EUR", "order_count": 1, "valid_order_count": 1, "gross_sales": "10"},
        ])
        recipient = object()
        report = build_report({"config": {"report_type": "sales"}}, recipient)
        self.assertEqual(query.call_args.args[0].user, recipient)
        raw = query.call_args.args[1]
        self.assertEqual(raw["dataset"], "sales")
        yesterday = timezone.localdate(timezone=timezone.get_fixed_timezone(480)) - timedelta(days=1)
        self.assertEqual(raw["filters"], {"date_from": yesterday.isoformat(), "date_to": yesterday.isoformat()})
        self.assertEqual(query.call_args.kwargs, {"use_cache": False})
        self.assertEqual({row["currency"] for row in report["sections"][0]["rows"]}, {"USD", "EUR"})

    @patch("apps.integrations.feishu_reports.query_dataset")
    def test_comprehensive_queries_all_sources_and_marks_partial_access(self, query):
        def answer(request, raw, **kwargs):
            if raw["dataset"] == "sales":
                raise PermissionDenied()
            if raw["dataset"].startswith("inventory"):
                self.assertEqual(raw["filters"], {"date_to": (timezone.localdate(timezone=timezone.get_fixed_timezone(480)) - timedelta(days=1)).isoformat()})
            row = {metric: 1 for metric in METRICS[raw["dataset"]]}
            if "currency" in raw["dimensions"]:
                row["currency"] = "USD"
            return {"rows": [row], "config": {"filters": raw["filters"]}, "truncated": True, "refreshed_at": None}
        query.side_effect = answer
        report = build_report({"config": {"report_type": "comprehensive"}}, object())
        self.assertEqual(len(report["sections"]), 6)
        self.assertEqual(report["sections"][0]["status"], "no_permission")
        self.assertTrue(report["sections"][-1]["truncated"])
        self.assertIn("流水净额 1", report["summary"])
        self.assertNotIn("order_count", METRICS["sales_skus"])

    @patch("apps.integrations.feishu_reports.query_dataset", side_effect=RuntimeError("not-a-real-source-error"))
    def test_source_failure_is_not_mislabeled_as_permission_error(self, _query):
        with self.assertRaises(ValidationError):
            build_report({"config": {"report_type": "sales"}}, object())

    @patch("apps.integrations.feishu_reports.timezone.now", return_value=datetime(2026, 9, 30, 17, 0, tzinfo=UTC))
    def test_report_windows_use_beijing_date_at_utc_boundary(self, _now):
        self.assertEqual(_window({}), {"date_from": "2026-09-30", "date_to": "2026-09-30"})
        self.assertEqual(_window({"schedule": "weekly"}), {"date_from": "2026-09-24", "date_to": "2026-09-30"})
        self.assertEqual(_window({"schedule": "monthly"}), {"date_from": "2026-09-01", "date_to": "2026-09-30"})

    def test_rejects_invalid_or_excessive_date_window(self):
        for filters in [{"date_from": "not-a-date"}, {"date_from": "2026-09-30", "date_to": "2026-09-01"}, {"date_from": "2026-08-01", "date_to": "2026-09-30"}]:
            with self.assertRaises(ValidationError):
                _window({"filters": filters})

    @patch("apps.integrations.feishu_reports.query_dataset", side_effect=PermissionDenied())
    def test_refuses_when_every_source_is_forbidden(self, _query):
        with self.assertRaises(PermissionDenied):
            build_report({"config": {"report_type": "sales"}}, object())

    def test_csv_has_bom_quotes_fields_and_neutralizes_formula_cells(self):
        csv_bytes = report_csv({"title": "=1+1", "generated_at": "now", "sections": [{"title": "Sales", "status": "available", "rows": [{"currency": "USD", "gross_sales": "-10"}], "note": "@malicious"}]})
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
        self.assertEqual(rows[0][1], "'=1+1")
        self.assertIn("'-10", [cell for row in rows for cell in row])
        self.assertIn("'@malicious", [cell for row in rows for cell in row])

    def test_rejects_extra_configuration(self):
        with self.assertRaises(ValidationError):
            build_report({"config": {"report_type": "sales", "filters": {"store_id": "1"}}}, object())


@pytest.mark.django_db
def test_real_report_obeys_tenant_store_scope_and_cancelled_status():
    from apps.masterdata.models import StoreMaster
    from apps.permissions.models import DataScope
    from tests.test_sales_management import NOW, create_scope, create_order, grant, user_for
    tenant, platform, visible, _ = create_scope("feishu-real-report")
    hidden = StoreMaster.objects.create(tenant=tenant, platform=platform, code="hidden", name="hidden", country_code="PH", currency="PHP", timezone="Asia/Manila")
    create_order(tenant, visible, "fs-visible", "125")
    void = create_order(tenant, visible, "fs-void", "75"); void.normalized_status = "cancelled"; void.save()
    create_order(tenant, hidden, "fs-hidden", "999")
    foreign, _, foreign_store, _ = create_scope("feishu-foreign-report")
    create_order(foreign, foreign_store, "fs-foreign", "9000")
    user = user_for(tenant, "fs-report-recipient")
    grant(user, "reports.view")
    grant(user, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [str(visible.pk)]})
    rule = {"config": {"report_type": "sales", "filters": {"date_from": NOW.date().isoformat(), "date_to": NOW.date().isoformat()}}}
    report = build_report(rule, user)
    row = report["sections"][0]["rows"][0]
    assert row["order_count"] == 2 and row["valid_order_count"] == 1
    assert row["currency"] == "PHP" and Decimal(row["gross_sales"]) == Decimal("125")
    assert "999" not in report["summary"] and "9000" not in report["summary"]
    denied = user_for(tenant, "fs-no-report-permission")
    with pytest.raises(PermissionDenied):
        build_report(rule, denied)


@pytest.mark.django_db
def test_comprehensive_all_six_real_queries_execute_with_numeric_metrics():
    from tests.test_sales_management import NOW, create_scope, create_order, grant, user_for
    tenant, _, store, _ = create_scope("feishu-six-sources")
    create_order(tenant, store, "fs-six", "100")
    user = user_for(tenant, "fs-six-recipient")
    for code in ["reports.view", "sales_management.view", "finance.view", "products.cost.view"]:
        grant(user, code)
    report = build_report({"config": {"report_type": "comprehensive", "filters": {"date_from": NOW.date().isoformat(), "date_to": NOW.date().isoformat()}}}, user)
    assert len(report["sections"]) == 6
    assert all(section["status"] in {"available", "no_data"} for section in report["sections"])
    assert report["sections"][0]["rows"][0]["valid_order_count"] == 1
    assert report["sections"][1]["rows"][0]["units_sold"] == 2
