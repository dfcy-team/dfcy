import pytest

from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for


@pytest.mark.django_db
def test_order_sorting_is_numeric_global_stable_and_tenant_scoped():
    tenant, _, store, _ = create_scope("sort-orders")
    low = create_order(tenant, store, "low", "9")
    high = create_order(tenant, store, "high", "100")
    high.items.update(quantity=12)
    other, _, other_store, _ = create_scope("sort-hidden")
    create_order(other, other_store, "hidden", "999")
    user = user_for(tenant, "sort-viewer")
    grant(user, "sales_management.orders.view")
    client = client_for(user)
    path = "/api/internal/sales-management/orders/"
    for field in ("order_total_amount", "item_count"):
        for ordering, expected in [(field, low.id), ("-" + field, high.id)]:
            response = client.get(path, {"ordering": ordering, "page_size": 1})
            assert response.status_code == 200
            assert response.json()["data"]["results"][0]["id"] == expected
        response = client.get(path, {"ordering": "-" + field, "page_size": 1, "page": 2})
        assert response.json()["data"]["results"][0]["id"] == low.id
    for field in (
        "platform", "store.name", "store.region", "external_order_id",
        "raw_status", "normalized_status", "created_at_utc", "currency",
    ):
        response = client.get(path, {"ordering": field, "external_order_id": "high"})
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["data"]["results"]] == [high.id]
    assert client.get(path, {"ordering": "tenant_id"}).status_code == 400
    assert client.get(path, {"ordering": "--item_count"}).status_code == 400
