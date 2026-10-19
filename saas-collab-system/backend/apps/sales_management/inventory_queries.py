"""MySQL plan control for measured broad inventory identity and date reads."""

from django.db.models.sql.datastructures import BaseTable
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
    """Rank before mapping/status/scope filters; hint only the ranking clone."""
    from django.db.models import F, Subquery, Window
    from django.db.models.functions import RowNumber
    ranked = prefer_country_inventory_cover(source).order_by().annotate(
        identity_rank=Window(expression=RowNumber(),
            partition_by=[F('site_code'), F('warehouse_id'), F('source_sku')],
            order_by=[F('snapshot_at_utc').desc(), F('pk').desc()]))
    ids = ranked.filter(identity_rank=1).values('pk')
    return source.filter(pk__in=Subquery(ids))
