"""Select the latest eligible complete run per warehouse before filtering SKUs."""

from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber

from apps.integrations.models import SyncRun


def published_inventory_filter(tenant_id, *, country_code=None, as_of=None):
    warehouse = "sync_job__warehouse_authorization__warehouse"
    runs = SyncRun.objects.filter(
        tenant_id=tenant_id, status="success", failed_count=0, finished_at__isnull=False,
        sync_job__resource_type="inventory_snapshot",
        sync_job__integration_config__platform="jifeng_wms",
        sync_job__warehouse_authorization__tenant_id=tenant_id,
        **{f"{warehouse}__tenant_id": tenant_id},
        masked_log__decision_source__started_from_initial_cursor=True,
        masked_log__decision_source__ended_without_cursor=True,
        masked_log__decision_source__all_records_valid=True,
    )
    if country_code:
        runs = runs.filter(**{f"{warehouse}__country_code__iexact": country_code})
    if as_of:
        runs = runs.filter(finished_at__lte=as_of)
    latest = runs.annotate(
        warehouse_rank=Window(
            expression=RowNumber(), partition_by=[F(f"{warehouse}_id")],
            order_by=[F("finished_at").desc(), F("pk").desc()],
        ),
    ).filter(warehouse_rank=1).order_by()
    scope = Q(pk__in=[])
    for run_id, warehouse_id in latest.values_list("pk", f"{warehouse}_id"):
        scope |= Q(source_run_id=run_id, warehouse_id=warehouse_id)
    return scope
