from importlib import import_module

import pytest
from django.db import migrations


migration = import_module("apps.development.migrations.0002_product_sales_summary_view")


def test_sales_summary_view_operation_matches_vm_migration_contract():
    operation = migration.Migration.operations[0]

    assert isinstance(operation, migrations.RunPython)
    assert operation.atomic is None
    assert operation.code is migration.create_sales_summary_view
    assert operation.reverse_code is migration.drop_sales_summary_view


class _Operations:
    @staticmethod
    def quote_name(value):
        return f'"{value}"'


class _Connection:
    def __init__(self, vendor):
        self.vendor = vendor
        self.ops = _Operations()


class _SchemaEditor:
    def __init__(self, vendor):
        self.connection = _Connection(vendor)
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)


@pytest.mark.parametrize(
    ("vendor", "dialect_fragment"),
    [
        ("mysql", "DATE_SUB(CURRENT_DATE, INTERVAL 29 DAY)"),
        ("sqlite", "DATE('now', '-29 day')"),
        ("postgresql", "CURRENT_DATE - INTERVAL '29 days'"),
    ],
)
def test_sales_summary_view_sql_keeps_backend_dialects(vendor, dialect_fragment):
    schema_editor = _SchemaEditor(vendor)

    migration.create_sales_summary_view(None, schema_editor)

    assert schema_editor.statements[0] == 'DROP VIEW IF EXISTS "v_product_sales_summary"'
    assert "CREATE VIEW \"v_product_sales_summary\" AS" in schema_editor.statements[1]
    assert dialect_fragment in schema_editor.statements[1]
    assert "AS summary_key" in schema_editor.statements[1]
