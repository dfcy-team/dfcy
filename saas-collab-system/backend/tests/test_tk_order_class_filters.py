import pytest
from apps.integrations.order_field_mapping import enrich_order_fields
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for


@pytest.mark.parametrize("platform,flags,expected", [
    ("tiktok", {"is_sample_order": True}, "free"),
    ("tiktok", {"is_sample_order": False, "is_refundable_sample": True}, "refundable"),
    ("tiktok", {"is_sample_order": False, "is_refundable_sample": False}, "none"),
    ("tiktok", {"is_sample_order": False}, None),
    ("shopee", {"is_sample_order": True}, None),
])
def test_sample_evidence(platform, flags, expected):
    assert enrich_order_fields(platform, flags, {})["observed_fields"].get("tk_sample_kind") == expected


@pytest.mark.django_db
def test_order_type_is_optional_and_needs_positive_evidence():
    tenant, platform, store, _ = create_scope("tk-filter")
    order = create_order(tenant, store, "tk-filter-order")
    platform.platform_type = "tiktok"
    platform.save()
    actor = user_for(tenant, "tk-filter-view")
    grant(actor, "sales_management.orders.view")
    api = client_for(actor)
    def count(**filters):
        result = api.get("/api/internal/commerce/orders/", {"include_summary": "false", **filters})
        assert result.status_code == 200, result.data
        return result.json()["data"]["count"]
    assert count() == 1
    assert count(tk_order_type="sample") == count(tk_order_type="affiliate") == 0
    order.source_details = {"tk_sample_kind": "refundable"}
    order.save(update_fields=["source_details"])
    assert count(tk_order_type="sample") == 1
