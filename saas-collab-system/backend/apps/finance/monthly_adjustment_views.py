from datetime import date

from django.conf import settings
from django.db.models import Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.responses import success_response
from apps.accounts.models import CustomUser
from apps.masterdata.models import WarehouseMaster
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import permission_scope_configs
from apps.products.monthly_cost_models import MonthlyCostAdjustment


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def historical_sold_adjustments(request):
    if getattr(settings, "MONTHLY_PRODUCT_COST_FINANCE_ENABLED", False) is not True:
        return success_response({"enabled": False, "month": None, "rows": []})
    user = request.user
    if user.user_type != CustomUser.UserType.INTERNAL or not check_user_permission(user, "finance.view"):
        return Response({"success": False, "message": "finance.view permission required"}, status=403)
    month = request.query_params.get("month", "")
    try:
        if len(month) != 7:
            raise ValueError
        parsed = date.fromisoformat(month + "-01")
    except ValueError:
        return Response({"success": False, "message": "month must use YYYY-MM"}, status=400)
    configs = permission_scope_configs(user, "finance.view", {"warehouse_ids", "site_ids", "regions"},
        allowed_keys={"warehouse_ids", "site_ids", "regions"})
    if configs is None:
        warehouses = WarehouseMaster.objects.filter(tenant=user.tenant)
    else:
        from django.db.models import Q
        scope = Q(pk__in=[])
        for config in configs:
            if not any(k in config for k in ("warehouse_ids", "site_ids", "regions")):
                return Response({"success": False, "message": "warehouse scope required"}, status=403)
            condition = Q()
            if "warehouse_ids" in config:
                condition &= Q(pk__in=config["warehouse_ids"])
            if "regions" in config:
                condition &= Q(country_code__in=config["regions"])
            if "site_ids" in config:
                from apps.masterdata.models import CountrySiteMaster
                codes = CountrySiteMaster.objects.filter(tenant=user.tenant, pk__in=config["site_ids"]).values("country_code")
                condition &= Q(country_code__in=codes)
            scope |= condition
        warehouses = WarehouseMaster.objects.filter(tenant=user.tenant).filter(scope)
    qs = MonthlyCostAdjustment.objects.filter(tenant=user.tenant, status="allocated", effective_month=parsed,
        warehouse__in=warehouses).values("warehouse__country_code", "warehouse_id", "warehouse__name").annotate(
            inventory_amount=Sum("inventory_amount"), sold_amount=Sum("sold_amount"), delta_amount=Sum("delta_amount"))
    def amount(value):
        return format(value, ".4f") if value is not None else None
    rows = [{"country": r["warehouse__country_code"], "warehouse_id": r["warehouse_id"],
        "warehouse": r["warehouse__name"], "inventory_amount": amount(r["inventory_amount"]),
        "sold_amount": amount(r["sold_amount"]),
        "gross_profit_impact": amount(-r["sold_amount"] if r["sold_amount"] is not None else None),
        "delta_amount": amount(r["delta_amount"])} for r in qs]
    return success_response({"enabled": True, "month": month, "rows": rows,
        "allocation_note": "仓库级历史调整，未分配到店铺；不改变原订单毛利或库存"})
