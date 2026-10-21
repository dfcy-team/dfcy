"""Opt-in synthetic scale checks; restricted to an isolated SQLite test database."""
import json
import os
from pathlib import Path
from time import perf_counter

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError

from apps.accounts.models import InternalUserProfile
from apps.commerce.models import SalesOrder
from apps.integrations.feishu_reminders import input_data, preview
from apps.integrations.models import FeishuDelivery, FeishuIdentity
from tests.test_feishu_business_reminders import data_for, reminder_settings, scene
from tests.test_sales_management import grant, user_for

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("reminder_settings"),
              pytest.mark.skipif(os.getenv("RUN_FEISHU_REMINDER_BENCHMARK") != "1", reason="opt-in synthetic benchmark")]


def populate_synthetic_orders(target=100000):
    assert connection.vendor == "sqlite" and "memory" in str(connection.settings_dict["NAME"]), "Benchmark must use an in-memory test database"
    table = connection.ops.quote_name(SalesOrder._meta.db_table)
    fields = [field for field in SalesOrder._meta.concrete_fields if not field.primary_key]
    columns = ", ".join(connection.ops.quote_name(field.column) for field in fields)
    expressions = ", ".join(connection.ops.quote_name(field.column) + (" || %s" if field.name == "external_order_id" else "") for field in fields)
    current = SalesOrder.objects.count()
    assert current == 1
    step = 0
    with connection.cursor() as cursor:
        while current < target:
            amount = min(current, target - current)
            cursor.execute(f"INSERT INTO {table} ({columns}) SELECT {expressions} FROM {table} LIMIT %s", [f"-b{step}", amount])
            current += amount
            step += 1
    assert SalesOrder.objects.count() == target


def save_metrics(case, metrics):
    destination = os.getenv("FEISHU_REMINDER_BENCHMARK_OUTPUT")
    if destination:
        path = Path(destination)
        results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        results[case] = metrics
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def fact_queries(queries):
    return [query for query in queries if '"sales_order"' in query["sql"] and query["sql"].lstrip().upper().startswith("SELECT")]


def test_100k_orders_selected_100_records_and_50_recipients(scene):
    populate_synthetic_orders()
    recipient_ids = [scene["member"].pk]
    for index in range(49):
        member = user_for(scene["tenant"], f"synthetic-member-{index}")
        grant(member, "sales_management.orders.view")
        InternalUserProfile.objects.create(user=member, tenant=scene["tenant"], department=scene["department"])
        FeishuIdentity.objects.create(tenant=scene["tenant"], user=member, open_id=f"ou_synthetic_{index}")
        recipient_ids.append(member.pk)
    ids = list(SalesOrder.objects.order_by("pk").values_list("pk", flat=True)[:100])
    payload = input_data(data_for(scene, record_ids=ids, recipient_user_ids=recipient_ids))
    started = perf_counter()
    with CaptureQueriesContext(connection) as captured:
        result = preview(scene["actor"], payload)
    elapsed = perf_counter() - started
    facts = fact_queries(captured.captured_queries)
    assert result["can_send"]
    assert len(result["recipients"]) == 50
    assert all(item["count"] == 100 for item in result["recipients"])
    assert len(facts) == 2
    assert all("COUNT(" in query["sql"].upper() and "LIMIT 10001" in query["sql"].upper() for query in facts)
    assert not FeishuDelivery.objects.exists()
    save_metrics("selected_100x50", {"database": "SQLite in-memory synthetic", "source_rows": 100000,
        "selected_rows": 100, "recipients": 50, "elapsed_seconds": round(elapsed, 4),
        "sql_queries": len(captured), "fact_count_queries": len(facts), "fact_rows_loaded": 0, "external_sends": 0})


def test_100k_order_filtered_range_stops_at_cardinality_gate(scene):
    populate_synthetic_orders()
    payload = input_data(data_for(scene, mode="filtered", record_ids=[], filters={"date_from": "2026-08-01", "date_to": "2026-08-31"}))
    started = perf_counter()
    with CaptureQueriesContext(connection) as captured, pytest.raises(ValidationError, match="10000"):
        preview(scene["actor"], payload)
    elapsed = perf_counter() - started
    facts = fact_queries(captured.captured_queries)
    assert len(facts) == 1
    assert "LIMIT 10001" in facts[0]["sql"].upper()
    assert not FeishuDelivery.objects.exists()
    save_metrics("filtered_100k_rejected", {"database": "SQLite in-memory synthetic", "source_rows": 100000,
        "elapsed_seconds": round(elapsed, 4), "sql_queries": len(captured), "fact_count_queries": len(facts),
        "outcome": "rejected_above_10000", "fact_rows_loaded": 0, "external_sends": 0})
