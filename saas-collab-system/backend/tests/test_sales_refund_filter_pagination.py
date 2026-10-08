import hashlib

import pytest

from apps.commerce.models import RefundReturn
from tests.test_sales_management import NOW, client_for, create_order, create_run, create_scope, grant, user_for


def add_refund(tenant, platform, store, order, suffix, status):
    return RefundReturn.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        sales_order=order,
        source_run=create_run(tenant, "refund_return", suffix),
        external_return_id=f"RETURN-{suffix}",
        case_type="refund_only",
        raw_status=status.upper(),
        normalized_status=status,
        requested_at_utc=NOW,
        updated_at_utc=NOW,
        currency=store.currency,
        refund_amount="10.0000",
        payload_hash=hashlib.sha256(suffix.encode()).hexdigest(),
    )


@pytest.mark.django_db
def test_refund_filters_keep_orders_unique_and_preserve_independent_semantics():
    tenant, platform, store, _ = create_scope("refund-page")
    matching = create_order(tenant, store, "refund-page-matching")
    matching_second = create_order(tenant, store, "refund-page-matching-second")
    no_refund = create_order(tenant, store, "refund-page-none")
    unrelated_tenant, _, unrelated_store, _ = create_scope("refund-page-hidden")
    unrelated_order = create_order(unrelated_tenant, unrelated_store, "refund-page-hidden")

    add_refund(tenant, platform, store, matching, "refund-page-a", "completed")
    add_refund(tenant, platform, store, matching, "refund-page-b", "completed")
    add_refund(tenant, platform, store, matching_second, "refund-page-c", "accepted")
    add_refund(unrelated_tenant, unrelated_order.platform, unrelated_store, unrelated_order, "refund-page-hidden", "completed")
    viewer = user_for(tenant, "refund-page-viewer")
    grant(viewer, "sales_management.orders.view")
    client = client_for(viewer)

    for route in ("/api/internal/commerce/orders/", "/api/internal/sales-management/orders/"):
        matching_response = client.get(route, {"has_refund_return": "true", "page_size": 1, "include_summary": "false"})
        second_page = client.get(route, {"has_refund_return": "true", "page_size": 1, "page": 2, "include_summary": "false"})
        status_response = client.get(route, {"refund_status": "completed", "page_size": 10, "include_summary": "false"})
        no_refund_response = client.get(route, {"has_refund_return": "false", "page_size": 10, "include_summary": "false"})
        contradictory = client.get(route, {
            "has_refund_return": "false", "refund_status": "completed", "include_summary": "false",
        })

        assert matching_response.status_code == second_page.status_code == 200
        first = matching_response.json()["data"]
        second = second_page.json()["data"]
        assert first["count"] == second["count"] == 2
        assert len(first["results"]) == len(second["results"]) == 1
        assert {first["results"][0]["id"], second["results"][0]["id"]} == {matching.id, matching_second.id}
        assert first["results"][0]["id"] != second["results"][0]["id"]
        assert status_response.json()["data"]["count"] == 1
        assert [row["id"] for row in status_response.json()["data"]["results"]] == [matching.id]
        assert no_refund_response.json()["data"]["count"] == 1
        assert [row["id"] for row in no_refund_response.json()["data"]["results"]] == [no_refund.id]
        assert contradictory.json()["data"]["count"] == 0
