"""Bounded warehouse-page synchronization summaries over existing facts."""
from django.db.models import Max, Min, Q
from django.db.models.sql.datastructures import BaseTable

from apps.commerce.models import InventorySnapshot


class _WarehouseSummaryCover(BaseTable):
    def as_sql(self, compiler, connection):
        sql, params = super().as_sql(compiler, connection)
        if connection.vendor == 'mysql':
            sql += ' FORCE INDEX (' + connection.ops.quote_name('idx_inv_latest_cover') + ')'
        return sql, params


def latest_warehouse_snapshots(tenant_id, warehouse_ids):
    if not warehouse_ids:
        return {}
    source = InventorySnapshot.objects.filter(tenant_id=tenant_id, warehouse_id__in=warehouse_ids)
    alias = source.query.base_table
    table = source.query.alias_map[alias]
    source.query.alias_map[alias] = _WarehouseSummaryCover(table.table_name, table.table_alias)
    # Scan the narrow covering index once for the page, rather than fetching
    # and sorting every historical row separately for each warehouse.
    moments = source.order_by().values('warehouse_id').annotate(moment=Max('snapshot_at_utc'))
    criteria = Q(pk__in=[])
    for row in moments:
        criteria |= Q(warehouse_id=row['warehouse_id'], snapshot_at_utc=row['moment'])
    ids = InventorySnapshot.objects.filter(tenant_id=tenant_id).filter(criteria).order_by().values(
        'warehouse_id').annotate(snapshot_id=Min('pk'))
    # Timestamp ties previously had no specified order; select a stable row.
    snapshots = InventorySnapshot.objects.filter(
        tenant_id=tenant_id, pk__in=[row['snapshot_id'] for row in ids],
    ).select_related('source_run')
    return {row.warehouse_id: row for row in snapshots}
