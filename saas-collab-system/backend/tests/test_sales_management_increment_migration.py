"""Regression evidence for the additive sales-management production migration."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_main_sales_history_migrates_forward_without_recreating_operating_tables():
    assert connection.vendor == "sqlite", "Migration regression must never use a business database."
    before = [("sales_management", "0005_salesninesnapshot")]
    after = [("sales_management", "0007_registration_and_aftersales_permissions")]
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    before_state = [node for node in leaves if node[0] != "sales_management"] + before
    try:
        executor.migrate(before_state)
        old_apps = executor.loader.project_state(before_state).apps
        tenant = old_apps.get_model("tenants", "Tenant").objects.create(
            name="Synthetic migration", code="synthetic-sales-migration"
        )
        country = old_apps.get_model("masterdata", "CountrySiteMaster").objects.create(
            tenant_id=tenant.pk,
            code="synthetic-ph",
            name="Synthetic PH",
            country_code="PH",
            platform="synthetic",
        )
        user = old_apps.get_model("accounts", "CustomUser").objects.create(
            username="synthetic-sales-migration",
            user_type="internal",
            tenant_id=tenant.pk,
        )
        old_order = old_apps.get_model("sales_management", "OperatingOrder").objects.create(
            tenant_id=tenant.pk,
            country_id=country.pk,
            created_by_id=user.pk,
            number="SYNTHETIC-ORDER-1",
            country_code_snapshot="PH",
            source_kind="new_goods",
            order_date="2026-11-04",
            creation_key="synthetic-create-key",
            request_hash="a" * 64,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        current = new_apps.get_model("sales_management", "OperatingOrder").objects.get(pk=old_order.pk)
        assert current.number == "SYNTHETIC-ORDER-1"
        assert new_apps.get_model("sales_management", "OrderRegistration").objects.count() == 0
        assert new_apps.get_model("sales_management", "AftersalesCase").objects.count() == 0

        tables = connection.introspection.table_names()
        assert tables.count("sales_management_operatingorder") == 1
        assert "sales_management_orderregistration" in tables
        assert "sales_management_aftersalescase" in tables
    finally:
        MigrationExecutor(connection).migrate(leaves)
