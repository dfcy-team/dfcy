"""Warehouse SKU mapping over existing inventory facts; no duplicate catalogue."""

from django.db import connection, transaction
from django.db.models import F, Q, Window
from django.db.models.functions import Collate, RowNumber
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.commerce.inventory_sku_mapping import resolve_inventory_sku
from apps.commerce.models import InventorySnapshot
from apps.common.query import pagination_query
from apps.common.responses import paginated_data, success_response
from apps.integrations.models import IntegrationAuditLog
from apps.masterdata.models import WarehouseMaster
from apps.permissions.ui_p6_scopes import (
    INTEGRATION_SCOPE_KEYS,
    _validate_integration_configs,
    permission_scope_configs,
)
from apps.products.models import ProductSKU

from .permissions import permission_class


VIEW = "integrations.product_mapping.view"
CONFIRM = "integrations.product_mapping.confirm"


def _facts(user):
    return InventorySnapshot.objects.filter(
        tenant=user.tenant,
        warehouse__tenant=user.tenant,
        source_run__sync_job__tenant=user.tenant,
        source_run__sync_job__integration_config__tenant=user.tenant,
        source_run__sync_job__integration_config__platform="jifeng_wms",
        source_run__sync_job__resource_type="inventory_snapshot",
    ).filter(Q(internal_sku__isnull=True) | Q(internal_sku__tenant=user.tenant))


def _scoped(user, code):
    rows = _facts(user)
    configs = permission_scope_configs(user, code, INTEGRATION_SCOPE_KEYS)
    if configs is None:
        return rows
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    for config in configs:
        if "store_ids" in config:
            continue  # A shop grant cannot authorize a warehouse.
        branch = Q()
        fields = {
            "warehouse_ids": "warehouse_id",
            "regions": "site_code",
            "platforms": "source_run__sync_job__integration_config__platform",
            "environments": "source_run__sync_job__integration_config__environment",
            "integration_config_ids": "source_run__sync_job__integration_config_id",
            "resource_types": "source_run__sync_job__resource_type",
        }
        for key, field in fields.items():
            if key in config:
                branch &= Q(**{f"{field}__in": config[key]})
        allowed |= branch
    return rows.filter(allowed)


def _history(user, row):
    # Exact comparison also on MySQL installations with case-insensitive collation.
    return [
        item
        for item in _facts(user)
        .filter(
            warehouse_id=row.warehouse_id,
            site_code=row.site_code,
            source_sku=row.source_sku,
        )
        .only("id", "source_sku", "internal_sku_id")
        if item.source_sku == row.source_sku
    ]


def _latest_facts(rows):
    """Select the newest row per case-sensitive warehouse SKU in one scan."""
    exact_source_sku = Collate(
        F("source_sku"),
        {"mysql": "utf8mb4_bin", "postgresql": "C", "sqlite": "BINARY"}[connection.vendor],
    )
    return rows.annotate(
        _latest_rank=Window(
            expression=RowNumber(),
            partition_by=[F("warehouse_id"), F("site_code"), exact_source_sku],
            order_by=[F("snapshot_at_utc").desc(), F("id").desc()],
        )
    ).filter(_latest_rank=1)


class WarehouseRowSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name")
    warehouse_code = serializers.CharField(source="warehouse.code")
    internal_sku_code = serializers.CharField(source="internal_sku.sku_code", default="")
    internal_legacy_sku_code = serializers.CharField(source="internal_sku.legacy_sku_code", default="")

    class Meta:
        model = InventorySnapshot
        fields = [
            "id",
            "warehouse_id",
            "warehouse_name",
            "warehouse_code",
            "site_code",
            "source_sku",
            "internal_sku_id",
            "internal_sku_code",
            "internal_legacy_sku_code",
            "snapshot_at_utc",
            "on_hand_qty",
            "reserved_qty",
            "available_qty",
        ]


@api_view(["GET"])
@permission_classes([permission_class(VIEW)])
def warehouse_skus(request):
    rows = _scoped(request.user, VIEW)
    options = list(
        rows.order_by("warehouse__code")
        .values("warehouse_id", "warehouse__name", "warehouse__code")
        .distinct()
    )
    rows = _latest_facts(rows)
    warehouse = request.query_params.get("warehouse_id")
    if warehouse:
        if not str(warehouse).isdigit() or int(warehouse) <= 0:
            raise ValidationError({"warehouse_id": "请选择有效仓库。"})
        rows = rows.filter(warehouse_id=warehouse)
    search = request.query_params.get("search", "").strip()
    if search:
        rows = rows.filter(
            Q(source_sku__icontains=search)
            | Q(internal_sku__sku_code__icontains=search)
            | Q(internal_sku__legacy_sku_code__icontains=search)
        )
    status = request.query_params.get("status", "")
    if status not in ("", "mapped", "unmapped"):
        raise ValidationError({"status": "请选择已关联或未关联。"})
    if status:
        rows = rows.filter(internal_sku__isnull=status == "unmapped")
    page, size = pagination_query(request)
    data = paginated_data(
        request,
        rows.select_related("warehouse", "internal_sku").order_by("warehouse_id", "source_sku", "id"),
        WarehouseRowSerializer,
        page=page,
        page_size=size,
    )
    data["warehouse_options"] = [
        {
            "value": row["warehouse_id"],
            "label": f'{row["warehouse__name"]}（{row["warehouse__code"]}）',
        }
        for row in options
    ]
    return success_response(data)


@api_view(["GET", "PATCH"])
@permission_classes([permission_class(VIEW)])
def warehouse_sku_mapping(request, pk):
    if request.method == "GET":
        row = get_object_or_404(_scoped(request.user, VIEW).select_related("warehouse"), pk=pk)
        ids = sorted({item.internal_sku_id for item in _history(request.user, row) if item.internal_sku_id})
        target, rule = resolve_inventory_sku(
            tenant=request.user.tenant,
            warehouse=row.warehouse,
            source_sku=row.source_sku,
            seller_sku=row.seller_sku,
        )
        search = request.query_params.get("search", "").strip()
        candidates = ProductSKU.objects.filter(tenant=request.user.tenant, is_active=True)
        if search:
            candidates = candidates.filter(
                Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search)
            )
        else:
            candidates = candidates.filter(pk__in=ids + ([target] if target else []))
        return success_response(
            {
                "current_sku_ids": ids,
                "suggested_sku_id": target,
                "rule": rule,
                "candidates": list(
                    candidates.order_by("sku_code").values("id", "sku_code", "legacy_sku_code")[:20]
                ),
            }
        )

    # Explicit confirm grant, not the generic edit or view permission.
    if not permission_class(CONFIRM)().has_permission(request, None):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("缺少 SKU 映射确认权限。")
    payload = ConfirmSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    values = payload.validated_data
    with transaction.atomic():
        row = get_object_or_404(_scoped(request.user, CONFIRM), pk=pk)
        WarehouseMaster.objects.select_for_update().get(pk=row.warehouse_id, tenant=request.user.tenant)
        history = _history(request.user, row)
        before = sorted({item.internal_sku_id for item in history if item.internal_sku_id})
        if before != sorted(set(values["expected_sku_ids"])):
            raise ValidationError("映射已变化，请刷新后重新确认。")
        # All affected facts must be inside both the read and confirm grants.
        ids = [item.id for item in history]
        if (
            _scoped(request.user, CONFIRM).filter(pk__in=ids).count() != len(ids)
            or _scoped(request.user, VIEW).filter(pk__in=ids).count() != len(ids)
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("当前权限未覆盖此仓库 SKU 的全部历史，不能修改共享映射。")
        sku = get_object_or_404(
            ProductSKU,
            pk=values["sku_id"],
            tenant=request.user.tenant,
            is_active=True,
        )
        changed = [item.id for item in history if item.internal_sku_id != sku.id]
        if changed:
            InventorySnapshot.objects.filter(pk__in=changed).update(internal_sku=sku)
            IntegrationAuditLog.objects.create(
                tenant=request.user.tenant,
                integration_config=row.source_run.sync_job.integration_config,
                actor=request.user,
                action="inventory_manual_sku_link",
                result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={
                    "warehouse_id": row.warehouse_id,
                    "snapshot_id": row.id,
                    "before_sku_ids": before,
                    "after_sku_id": sku.id,
                    "updated_count": len(changed),
                },
            )
        return success_response({"updated_count": len(changed), "internal_sku_id": sku.id})


class ConfirmSerializer(serializers.Serializer):
    sku_id = serializers.IntegerField(min_value=1)
    expected_sku_ids = serializers.ListField(child=serializers.IntegerField(min_value=1))
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if value is not True or self.initial_data.get("confirmed") is not True:
            raise serializers.ValidationError("请明确确认该仓库 SKU 的关联。")
        return value
