"""Incrementally refresh bounded calendar-month blocks of permission-scoped daily totals."""
import hashlib
import json
from datetime import date, timedelta

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .datasets import DATASETS, VERSION, query_dataset, scope_fingerprint, selected_permission


def daily_blocks(request, config):
    dataset = DATASETS[config["dataset"]]
    permission = selected_permission(request.user, dataset)
    scope = scope_fingerprint(request.user, dataset, permission, config["dataset"])
    cursor = date.fromisoformat(config["filters"]["date_from"])
    end = date.fromisoformat(config["filters"]["date_to"])
    result = None
    rows, labels, block_times = [], {}, []
    all_cached = True
    persistent = getattr(settings, "REPORT_AGGREGATE_BLOCK_CACHE", True) and config["filters"].get("sku_mode") != "related"
    if persistent:
        from .models import ReportAggregateBlock
    while cursor <= end:
        check_active = getattr(request, "check_active", None)
        if check_active:
            check_active()
        next_month = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        last = min(end, next_month - timedelta(days=1))
        block = {**config, "filters": {**config["filters"], "date_from": cursor.isoformat(), "date_to": last.isoformat()}}
        key = hashlib.sha256(json.dumps([VERSION,"daily-block-v1",request.user.tenant_id,request.user.pk,scope,block],sort_keys=True,default=str).encode()).hexdigest()
        now = timezone.now()
        cached = ReportAggregateBlock.objects.filter(cache_key=key,tenant=request.user.tenant,requested_by=request.user,expires_at__gt=now).values_list("result",flat=True).first() if persistent else None
        if cached is not None:
            result = cached
        else:
            result = query_dataset(request,block,limit=20000)
            current_permission = selected_permission(request.user, dataset)
            if current_permission != permission or scope_fingerprint(request.user,dataset,current_permission,config["dataset"]) != scope:
                raise PermissionDenied("权限在汇总期间发生变化，请重新查询。")
            all_cached = all_cached and result["cached"]
            if result["truncated"]:
                raise ValidationError("数据分组超出安全范围，请选择国家、店铺或币种后重试。")
            result = json.loads(json.dumps(result,cls=DjangoJSONEncoder))
            # Corrections are eventually refreshed even in historic months.
            # Recent/month-to-date blocks expire sooner for daily incremental refresh.
            ttl = 60 if last >= now.date()-timedelta(days=31) else 3600
            if persistent:
                ReportAggregateBlock.objects.update_or_create(cache_key=key,defaults={"tenant":request.user.tenant,"requested_by":request.user,"result":result,"expires_at":now+timedelta(seconds=ttl)})
        rows.extend(result["rows"])
        if len(rows)>20000:
            raise ValidationError("全年分组超出安全范围，请选择国家、店铺或币种后重试。")
        for dimension, mapping in result.get("dimension_labels",{}).items():
            labels.setdefault(dimension,{}).update(mapping)
        block_times.append({"date_from":cursor.isoformat(),"date_to":last.isoformat(),"computed_at":result["computed_at"],"refreshed_at":result["refreshed_at"]})
        cursor=next_month
    return {**result,"rows":rows,"dimension_labels":labels,"cached":all_cached,"computed_at":timezone.now(),"refreshed_at":max((b["refreshed_at"] for b in block_times if b["refreshed_at"]),default=None),"aggregate_blocks":block_times}
