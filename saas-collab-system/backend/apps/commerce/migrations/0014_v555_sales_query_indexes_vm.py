"""V555 indexes on the actual VM commerce0013 chain; no cloud catalogue dependency.

MySQL secondary indexes are added online with LOCK=NONE. Existing exact indexes
are accepted, but all definitions are checked before the first DDL statement.
This forward migration intentionally has no automatic reverse operation.
"""
from django.db import migrations, models

INDEXES = (
    ('SalesOrder', 'idx_sales_store_stamp', ('store', 'updated_at_utc')),
    ('SalesOrderItem', 'idx_items_order_stamp', ('sales_order', 'updated_at')),
    ('SalesOrder', 'idx_sales_tenant_created_id', ('tenant', 'created_at_utc', 'id')),
)


def add_online_indexes(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor not in {'mysql', 'sqlite'}:
        raise RuntimeError('V555 VM index migration requires MySQL (SQLite for isolated tests only)')
    missing = []
    with connection.cursor() as cursor:
        for model_name, name, fields in INDEXES:
            model = apps.get_model('commerce', model_name)
            columns = tuple(model._meta.get_field(field).column for field in fields)
            if connection.vendor == 'mysql':
                cursor.execute('SHOW INDEX FROM ' + schema_editor.quote_name(model._meta.db_table))
                rows = sorted((row for row in cursor.fetchall() if row[2] == name), key=lambda row: row[3])
                if rows:
                    if tuple(row[4] for row in rows) != columns or any(len(row) < 15 or row[1] != 1 or row[5] != 'A' or row[7] is not None or row[10] != 'BTREE' or row[13] != 'YES' or row[14] is not None for row in rows):
                        raise RuntimeError('Existing V555 index definition differs: ' + name)
                    continue
            missing.append((model, name, fields, columns))
    previous_lock_wait = None
    if connection.vendor == 'mysql' and missing:
        with connection.cursor() as cursor:
            cursor.execute('SELECT @@SESSION.lock_wait_timeout')
            previous_lock_wait = cursor.fetchone()[0]
            cursor.execute('SET SESSION lock_wait_timeout = 15')
    try:
        for model, name, fields, columns in missing:
            if connection.vendor == 'mysql':
                quote = schema_editor.quote_name
                schema_editor.execute('ALTER TABLE ' + quote(model._meta.db_table)
                    + ' ADD INDEX ' + quote(name) + ' (' + ', '.join(map(quote, columns))
                    + '), ALGORITHM=INPLACE, LOCK=NONE')
            else:
                schema_editor.add_index(model, models.Index(fields=list(fields), name=name))
    finally:
        if previous_lock_wait is not None:
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION lock_wait_timeout = %s', [previous_lock_wait])



class Migration(migrations.Migration):
    atomic = False
    dependencies = [('commerce', '0013_salesorder_cancellation_pending')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(add_online_indexes)],
        state_operations=[migrations.AddIndex(model_name=model.lower(),
            index=models.Index(fields=list(fields), name=name)) for model, name, fields in INDEXES],
    )]
