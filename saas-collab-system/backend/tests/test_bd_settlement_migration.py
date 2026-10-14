"""Migration evidence using a disposable SQLite test database only."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_additive_settlement_migration_preserves_legacy_blank_creator_refund_and_hash():
    assert connection.vendor == "sqlite", "Settlement migration regression must never use a business DB."
    before = [("influencers", "0033_affiliate_estimated_commission_base")]
    after = [("influencers", "0034_affiliate_settlement_status")]
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        state = executor.loader.project_state(before).apps
        tenant = state.get_model("tenants", "Tenant").objects.create(name="Synthetic migration", code="synthetic-migration")
        model = state.get_model("influencers", "AffiliateOrderSnapshot")
        old = model.objects.create(tenant_id=tenant.pk, source="synthetic", source_row_key="a" * 64,
                                   row_hash="b" * 64, data_time="2026-08-16T12:00:00+00:00", shop_abbr="synthetic",
                                   site="PH", order_id="synthetic", sku_id="synthetic", product_id="synthetic",
                                   currency="PHP", creator_username="", order_status="completed", fully_returned="\u5426")
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_model = executor.loader.project_state(after).apps.get_model("influencers", "AffiliateOrderSnapshot")
        current = new_model.objects.get(pk=old.pk)
        assert current.settlement_status is None and current.row_hash == "b" * 64
        assert current.creator_username == "" and current.fully_returned == "\u5426"
        assert current.source_row_key == "a" * 64 and current.order_status == "completed"
        assert new_model._meta.get_field("fully_returned").get_default() == ""
        field = new_model._meta.get_field("settlement_status")
        assert field.null and field.max_length == 32
    finally:
        MigrationExecutor(connection).migrate(leaves)
