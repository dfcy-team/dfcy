"""Permission-scoped reads of observed 09:00 snapshots; never reconstruct history."""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.masterdata.models import StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from .scopes import filter_sales_queryset
from .snapshot_models import SalesNineSnapshot


def _number(raw, maximum, name):
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 19 or not 1 <= int(raw) <= maximum:
        raise ValidationError({name: "必须为有效正整数。"})
    return int(raw)


def _metric(snapshot, currency):
    if snapshot is None:
        return None
    return next((g for g in snapshot.groups if g["currency"] == currency), None)


def _baseline(snapshots, days, currency, zone):
    samples = [snapshots.get(day) for day in days]
    values = [_metric(s, currency) for s in samples]
    if any(s is None or s.timezone_name != zone for s in samples) or any(v is None for v in values):
        return {"sales_amount": None, "sample_count": sum(v is not None for v in values), "status": "missing_or_incompatible"}
    amount = sum(Decimal(v["sales_amount"]) for v in values) / len(values)
    return {"sales_amount": str(amount), "sample_count": len(values), "status": "unverified"}


class SalesNineSnapshotView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        allowed = {"date", "store_id", "platform", "region", "page", "page_size"}
        if set(request.query_params) - allowed or any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
            raise ValidationError({"filters": "参数不受支持或重复。"})
        today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE))
        try:
            day = date.fromisoformat(request.query_params.get("date") or today.isoformat())
        except ValueError as exc:
            raise ValidationError({"date": "日期必须使用 YYYY-MM-DD。"}) from exc
        if not date(1970, 1, 15) <= day <= today + timedelta(days=1):
            raise ValidationError({"date": "日期超出可查询范围。"})
        page = _number(request.query_params.get("page", "1"), 10000, "page")
        size = _number(request.query_params.get("page_size", "20"), 50, "page_size")
        stores = filter_sales_queryset(
            request.user, self.read_permission_code, StoreMaster.objects.filter(tenant=request.user.tenant),
            {"store_ids": "id", "platforms": "platform__platform_type", "regions": "country_code"},
            permission_cache=getattr(request, "_permission_resolution_cache", None),
        )
        sid = request.query_params.get("store_id")
        if sid:
            stores = stores.filter(pk=_number(sid, 9223372036854775807, "store_id"))
        if request.query_params.get("platform"):
            stores = stores.filter(platform__platform_type=request.query_params["platform"])
        if request.query_params.get("region"):
            stores = stores.filter(country_code__iexact=request.query_params["region"])
        start = (page - 1) * size
        store_page = list(stores.order_by("id")[start:start + size + 1])
        has_next = len(store_page) > size
        store_page = store_page[:size]
        # Previous natural Mon-Sun week, each day at local09:00, not full-day GMV.
        monday = day - timedelta(days=day.weekday())
        week = [monday - timedelta(days=7) + timedelta(days=i) for i in range(7)]
        needed = set(week + [day, day - timedelta(days=1), day - timedelta(days=7)])
        saved = {}
        for s in SalesNineSnapshot.objects.filter(tenant=request.user.tenant, store_id__in=[s.pk for s in store_page], business_date__in=needed):
            saved.setdefault(s.store_id, {})[s.business_date] = s
        rows = []
        for store in store_page:
            samples = saved.get(store.pk, {})
            current = samples.get(day)
            currencies = sorted({g["currency"] for sample in samples.values() for g in sample.groups})
            groups = []
            for currency in currencies:
                metric = _metric(current, currency)
                baselines = {
                    "previous_day": _baseline(samples, [day - timedelta(days=1)], currency, current.timezone_name if current else store.timezone),
                    "previous_week_same_day": _baseline(samples, [day - timedelta(days=7)], currency, current.timezone_name if current else store.timezone),
                    "previous_week_average": _baseline(samples, week, currency, current.timezone_name if current else store.timezone),
                }
                groups.append({"currency": currency, "sales_amount": metric["sales_amount"] if metric else None,
                               "order_count": metric["order_count"] if metric else None, "baselines": baselines})
            rows.append({"store_id": store.pk, "store_name": store.name, "country": store.country_code,
                         "timezone": current.timezone_name if current else store.timezone,
                         "business_date": day.isoformat(), "target_at": current.target_at.isoformat() if current else None,
                         "captured_at": current.captured_at.isoformat() if current else None,
                         "status": "unverified" if current else "missing",
                         "integrity_reason": current.integrity_reason if current else "未采样；不使用当前订单补造历史快照。",
                         "groups": groups})
        return success_response({"rows": rows, "page": page, "page_size": size, "has_next": has_next,
                                 "date": day.isoformat(), "comparison_allowed": False,
                                 "notices": ["店铺当地00:00至09:00的已采集非取消订单；09:00至09:05采样窗口。",
                                             "快照仅为系统当时观测值，源完整性未核验；不计算异常百分比或触发推送。",
                                             "上周日均需上个自然周7份同币种同时段快照齐全；缺样保持未知。"]})
