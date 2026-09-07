"""Exercise the scheduler-to-catalogue boundary with fixture-only upstream I/O."""

import pytest

from apps.integrations.adapters import MarketplaceProductAdapter
from apps.integrations.models import ConnectionCapability, MarketplaceProductMapping, SyncCheckpoint
from apps.integrations.sync_services import run_sync_job
from apps.listings.models import PlatformProductDetail
from tests.test_platform_product_ingestion import _fixture


pytestmark = pytest.mark.django_db


def test_real_product_run_paginates_persists_checkpoints_and_repeats_without_duplicates():
    context = _fixture(create_store_mapping_row=False)
    job = context["job"]
    job.resource_type = "platform_product"
    job.save(update_fields=["resource_type"])
    ConnectionCapability.objects.create(
        authorization=context["authorization"], capability_code="PRODUCT",
        read_enabled=True, write_enabled=False, status="active",
    )

    class FixtureUpstream:
        def __init__(self):
            self.cursors = []

        def preflight(self):
            # Credential/network checks have their own tests.  No live
            # credentials or HTTP request are needed for this integration.
            pass

        def fetch_products(self, cursor, _scope):
            self.cursors.append(str(cursor or ""))
            second = str(cursor or "") == "second"
            return {
                "records": [{
                    "platform_product_id": "P2" if second else "P1",
                    "platform_variant_id": "V2" if second else "V1",
                    "platform_sku": "UNKNOWN" if second else "NEW-INGEST",
                    "title": "Unmatched" if second else "Matched",
                    "platform_updated_at": "2026-09-05T10:00:00Z",
                }],
                "next_cursor": "" if second else "second",
            }

    for index in range(2):
        upstream = FixtureUpstream()
        adapter = MarketplaceProductAdapter(context["config"], client=upstream)
        run, created = run_sync_job(job, adapter=adapter, idempotency_key=f"product-review-{index}")
        assert created and run.status == "success", run.masked_error_message
        assert upstream.cursors == ["", "second"]
        assert run.fetched_count == 2 and run.failed_count == 0
        assert run.raw_envelopes.count() == 2
        assert SyncCheckpoint.objects.get(sync_job=job).last_success_run_id == run.id
    assert PlatformProductDetail.objects.filter(tenant=context["tenant"]).count() == 2
    matched = MarketplaceProductMapping.objects.get(platform_variant_id="V1")
    assert matched.mapping_source == "api_exact_match"
    assert matched.status == "mapped" and not matched.manually_confirmed
    assert matched.platform_detail.internal_sku_id == context["sku"].id
    pending = MarketplaceProductMapping.objects.get(platform_variant_id="V2")
    assert pending.status == "unmapped" and pending.platform_detail.internal_sku_id is None
