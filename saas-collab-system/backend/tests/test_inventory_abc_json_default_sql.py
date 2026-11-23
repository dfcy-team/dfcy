"""MySQL ALTER must retain a function expression, not a folded JSON literal."""
import importlib

from django.db.backends.mysql.base import DatabaseWrapper
from django.db.migrations.writer import MigrationWriter

from apps.masterdata.models import InventoryABCEntry


def migration_field():
    module = importlib.import_module('apps.masterdata.migrations.0028_alter_inventoryabcentry_evidence')
    return module.Migration('0028_alter_inventoryabcentry_evidence', 'masterdata').operations[0].field


def mysql_default_sql(field):
    # Rendering this constant function must not open a database connection.
    field = field.clone()
    field.set_attributes_from_name('evidence')
    field.model = InventoryABCEntry
    connection = DatabaseWrapper({'ENGINE': 'django.db.backends.mysql', 'NAME': 'not_connected',
                                  'OPTIONS': {}, 'TIME_ZONE': None}, alias='json_default_sql')
    connection.ensure_connection = lambda: (_ for _ in ()).throw(AssertionError('unexpected connection'))
    return connection.schema_editor(collect_sql=True).db_default_sql(field)


def test_runtime_and_unapplied_migration_share_empty_object_expression():
    runtime = InventoryABCEntry._meta.get_field('evidence')
    frozen = migration_field()
    assert MigrationWriter.serialize(runtime.db_default) == MigrationWriter.serialize(frozen.db_default)
    assert runtime.default is dict and frozen.default is dict
    assert runtime.blank is True and frozen.blank is True


def test_mysql_runtime_default_remains_function_expression():
    sql, params = mysql_default_sql(InventoryABCEntry._meta.get_field('evidence'))
    assert sql == '(JSON_OBJECT())'
    assert not params


def test_mysql_migration_default_remains_function_expression():
    sql, params = mysql_default_sql(migration_field())
    assert sql == '(JSON_OBJECT())'
    assert not params
