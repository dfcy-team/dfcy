"""Additive cost schema evidence, using a disposable SQLite database only."""

from decimal import Decimal

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_ads_migration_keeps_existing_commission_nulls_values_hashes_and_keys():
    assert connection.vendor == "sqlite", "Migration regression must never use a business DB."
    before = [("influencers", "0035_seed_bd_exchange_rates")]
    after = [("influencers", "0036_affiliate_actual_ads_commission")]
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    try:
        migration = executor.loader.get_migration(*after[0])
        assert len(migration.operations) == 1 and isinstance(migration.operations[0], migrations.AddField)
        executor.migrate(before)
        state = executor.loader.project_state(before).apps
        tenant = state.get_model("tenants", "Tenant").objects.create(name="Synthetic cost migration", code="synthetic-cost-migration")
        model = state.get_model("influencers", "AffiliateOrderSnapshot")
        ids = []
        for number, commission in enumerate((None, "0", "1.2345"), start=1):
            old = model.objects.create(
                tenant_id=tenant.pk, source="synthetic", source_row_key=str(number) * 64,
                row_hash="b" * 64, data_time="2026-08-16T12:00:00+00:00", shop_abbr="synthetic",
                site="PH", order_id=f"synthetic-{number}", sku_id="synthetic", product_id="synthetic",
                currency="PHP", creator_username="", order_status="delivered", actual_paid_commission=commission,
            )
            ids.append(old.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        model = executor.loader.project_state(after).apps.get_model("influencers", "AffiliateOrderSnapshot")
        rows = list(model.objects.filter(pk__in=ids).order_by("id"))
        assert [row.actual_paid_commission for row in rows] == [None, Decimal("0"), Decimal("1.2345")]
        assert all(row.actual_paid_shop_ads_commission is None and row.row_hash == "b" * 64 for row in rows)
        assert [row.source_row_key for row in rows] == [str(number) * 64 for number in (1, 2, 3)]
        assert all(row.creator_username == "" and row.order_status == "delivered" for row in rows)
        field = model._meta.get_field("actual_paid_shop_ads_commission")
        assert field.null and field.blank and not field.has_default()
        assert field.max_digits == 20 and field.decimal_places == 4
    finally:
        MigrationExecutor(connection).migrate(leaves)
