import pytest
from apps.integrations.order_field_mapping import enrich_order_fields
from apps.integrations.models import SyncCursor
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
def test_only_verified_days_are_negative():
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
    assert count(tk_sample_kind="unknown", tk_affiliation="unknown") == 1
    assert count(tk_affiliation="no") == 0
    job = order.source_run.sync_job
    job.resource_type = "affiliate_order"
    job.save(update_fields=["resource_type"])
    SyncCursor.objects.create(tenant=tenant, sync_job=job,
        cursor_key=f"affiliate-covered:{store.pk}:{order.business_date}", cursor_value=store.timezone)
    assert count(tk_affiliation="no") == 1
    assert count(tk_affiliation="unknown") == 0
