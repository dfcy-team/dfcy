"""MySQL plan control for measured broad inventory identity and date reads."""

from contextlib import contextmanager

from django.db.models.sql.datastructures import BaseTable, Join
from django.db.models.sql.where import AND


def is_broad_inventory_source(source):
    """Leave time, SKU, warehouse and joined permission predicates unhinted."""
    query = source.query
    base = query.base_table
    columns = set()

    def allowed(node):
        if getattr(node, "negated", False):
            return False
        if hasattr(node, "children"):
            return node.connector == AND and all(allowed(child) for child in node.children)
        lhs = getattr(node, "lhs", None)
        column = getattr(getattr(lhs, "target", None), "column", None)
        columns.add(column)
        if getattr(lhs, "alias", None) != base:
            return False
        if column == "tenant_id":
            return node.lookup_name == "exact" and type(node.rhs) is int
        if column == "source_run_id":
            return (
                node.lookup_name == "in" and isinstance(node.rhs, (list, tuple))
                and all(type(value) is int for value in node.rhs)
            )
        return False

    return allowed(query.where) and columns == {"tenant_id", "source_run_id"}


class _CoveringInventoryTable(BaseTable):
    def as_sql(self, compiler, connection):
        sql, params = super().as_sql(compiler, connection)
        if connection.vendor == "mysql":
            sql += " FORCE INDEX (" + connection.ops.quote_name("idx_inv_latest_cover") + ")"
        return sql, params


def prefer_inventory_cover(source):
    """Clone only a measured broad source; keep outer and selective SQL intact."""
    if source.model._meta.db_table != "inventory_snapshot" or not is_broad_inventory_source(source):
        return source
    clone = source.all()
    base_alias = clone.query.base_table
    base = clone.query.alias_map[base_alias]
    clone.query.alias_map[base_alias] = _CoveringInventoryTable(base.table_name, base.table_alias)
    return clone


def prefer_country_inventory_cover(source):
    """Measured country identity scan; reject row-sensitive or joined predicates."""
    from datetime import datetime
    query = source.query
    base = query.base_table
    columns = set()

    def allowed(node):
        if getattr(node, 'negated', False):
            return False
        if hasattr(node, 'children'):
            return node.connector == AND and all(allowed(child) for child in node.children)
        lhs = getattr(node, 'lhs', None)
        column = getattr(getattr(lhs, 'target', None), 'column', None)
        columns.add(column)
        if getattr(lhs, 'alias', None) != base:
            return False
        if column == 'tenant_id':
            return node.lookup_name == 'exact' and type(node.rhs) is int and node.rhs > 0
        if column in ('warehouse_id', 'source_run_id'):
            limit = 1000 if column == 'warehouse_id' else 2000
            return (node.lookup_name == 'in' and isinstance(node.rhs, (list, tuple))
                    and 0 < len(node.rhs) <= limit
                    and all(type(value) is int and value > 0 for value in node.rhs))
        return column == 'snapshot_at_utc' and node.lookup_name == 'lte' and isinstance(node.rhs, datetime)

    if (source.model._meta.db_table != 'inventory_snapshot' or not allowed(query.where)
            or columns != {'tenant_id', 'warehouse_id', 'source_run_id', 'snapshot_at_utc'}):
        return source
    clone = source.all()
    alias = clone.query.base_table
    table = clone.query.alias_map[alias]
    clone.query.alias_map[alias] = _CoveringInventoryTable(table.table_name, table.table_alias)
    return clone


def latest_country_inventory(source):
    return materialized_latest_inventory(source, prefer_country_inventory_cover(source))


def materialized_latest_inventory(source, ranking_source=None):
    """Resolve the exact latest identities once, including timestamp ties.

    Both passes operate on the identical scoped source. A later failed or
    unmapped record therefore cannot expose an older record from that source.
    """
    from django.db import connections
    from django.db.models import F
    connection = connections[source.db]
    ranking_source = source if ranking_source is None else ranking_source
    projected = ranking_source.order_by().annotate(
        latest_id=F('pk'), latest_site=F('site_code'),
        latest_warehouse=F('warehouse_id'), latest_sku=F('source_sku'),
        latest_at=F('snapshot_at_utc'),
    ).values('latest_id', 'latest_site', 'latest_warehouse', 'latest_sku', 'latest_at')
    from django.core.exceptions import EmptyResultSet
    try:
        sql, params = projected.query.get_compiler(using=source.db).as_sql()
    except EmptyResultSet:
        return source.none()
    statement = (
        'WITH scoped AS (' + sql + '), newest AS ('
        'SELECT latest_site, latest_warehouse, latest_sku, MAX(latest_at) AS newest_at '
        'FROM scoped GROUP BY latest_site, latest_warehouse, latest_sku) '
        'SELECT MAX(s.latest_id) FROM scoped s JOIN newest n ON '
        's.latest_site = n.latest_site AND s.latest_warehouse = n.latest_warehouse '
        'AND s.latest_sku = n.latest_sku AND s.latest_at = n.newest_at '
        'GROUP BY s.latest_site, s.latest_warehouse, s.latest_sku'
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        ids = [row[0] for row in cursor.fetchall()]
    return source.filter(pk__in=ids)


class _OrderTimeTable(BaseTable):
    def as_sql(self, compiler, connection):
        sql, params = super().as_sql(compiler, connection)
        if connection.vendor == 'mysql':
            sql += ' FORCE INDEX (' + connection.ops.quote_name('idx_sales_order_store_time') + ')'
        return sql, params


class _OrderTimeJoin(Join):
    def as_sql(self, compiler, connection):
        sql, params = super().as_sql(compiler, connection)
        if connection.vendor == 'mysql':
            head, separator, tail = sql.partition(' ON ')
            if separator:
                sql = head + ' FORCE INDEX (' + connection.ops.quote_name('idx_sales_order_store_time') + ', ' + connection.ops.quote_name('PRIMARY') + ')' + separator + tail
        return sql, params


def prefer_sales_order_time(source):
    """Keep bounded store/date reads ahead of the broad run status join."""
    from copy import copy

    clone = source.all()
    for alias, table in list(clone.query.alias_map.items()):
        if table.table_name != 'sales_order':
            continue
        if isinstance(table, BaseTable):
            clone.query.alias_map[alias] = _OrderTimeTable(table.table_name, table.table_alias)
        elif isinstance(table, Join):
            replacement = copy(table)
            replacement.__class__ = _OrderTimeJoin
            clone.query.alias_map[alias] = replacement
    return clone


@contextmanager
def eligible_inventory_orders(orders):
    """Reuse one bounded order selection across the inventory calculations."""
    from uuid import uuid4
    from django.db import connections
    from django.db.models import F
    from django.db.models.expressions import RawSQL

    connection = connections[orders.db]
    if connection.vendor != 'mysql':
        yield orders.values('pk')
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT @@transaction_read_only')
        read_only = bool(cursor.fetchone()[0])
    if read_only:
        yield orders.values('pk')
        return
    table = connection.ops.quote_name('tmp_inventory_orders_' + uuid4().hex)
    projected = orders.order_by().annotate(eligible_id=F('pk')).values('eligible_id')
    sql, params = projected.query.get_compiler(using=orders.db).as_sql()
    from django.db import OperationalError
    try:
        with connection.cursor() as cursor:
            cursor.execute('CREATE TEMPORARY TABLE ' + table + ' (PRIMARY KEY (eligible_id)) ENGINE=InnoDB AS ' + sql, params)
    except OperationalError as exc:
        if not exc.args or exc.args[0] not in (1792, 1142):
            raise
        yield orders.values('pk')
        return
    try:
        yield RawSQL('SELECT eligible_id FROM ' + table, ())
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute('DROP TEMPORARY TABLE IF EXISTS ' + table)
        except Exception:
            # Closing the connection also removes its private temporary tables.
            connection.close()
            raise
