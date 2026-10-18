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
