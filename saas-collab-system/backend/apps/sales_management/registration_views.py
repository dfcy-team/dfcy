import io
import csv
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.commerce.models import SalesOrder, ShipmentRecord
from apps.masterdata.models import StoreMaster
from apps.integrations.models import MarketplaceProductMapping
from apps.products.models import ProductSKU
from apps.permissions.api_permissions import DeclaredApplicationPermission

from .registration_models import OrderRegistration, RegistrationEvidence, RegistrationImportBatch
from .registration_services import (create_registration, edit_registration, registration_action,
                                    representation, scoped, store_for, upload_evidence, set_registration_deleted)
from .views import _pagination
from .scopes import filter_sales_queryset
from .registration_models import PendingOrderDetail
from .registration_import import run_import, registration_template
from .registration_rules import gcash_payment_date, gcash_remark


def filtered_registrations(qs, request, kind):
    if request.query_params.get("request_key"):
        qs = qs.filter(idempotency_key=request.query_params["request_key"], requested_by=request.user)
    for param, field in (("store_id", "store_id"), ("status", "status"), ("order_number", "order__external_order_id")):
        if request.query_params.get(param):
            if param == "store_id" and (not request.query_params[param].isdigit() or int(request.query_params[param]) <= 0):
                raise ValidationError("店铺编号无效。")
            qs = qs.filter(**{field: request.query_params[param]})
    if kind == "gcash" and request.query_params.get("type"):
        qs = qs.filter(payload__type=request.query_params["type"])
    dates = {}
    for param in ("created_from", "created_to"):
        value = request.query_params.get(param)
        if value:
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value or parsed == date.max:
                    raise ValueError()
                dates[param] = parsed
            except (ValueError, TypeError):
                raise ValidationError({param: "登记日期必须为YYYY-MM-DD格式。"}) from None
    if len(dates) == 2 and dates["created_from"] > dates["created_to"]:
        raise ValidationError("开始日期不能晚于结束日期。")
    for param, day in dates.items():
        boundary = datetime.combine(day + (timedelta(days=1) if param == "created_to" else timedelta()), time(), ZoneInfo("Asia/Shanghai"))
        qs = qs.filter(**{"created_at__lt" if param == "created_to" else "created_at__gte": boundary})
    if request.query_params.get("batch_id"):
        if not request.query_params["batch_id"].isdigit() or int(request.query_params["batch_id"]) <= 0:
            raise ValidationError("导入批次编号无效。")
        batch = get_object_or_404(RegistrationImportBatch, pk=request.query_params["batch_id"], tenant=request.user.tenant,
                                  kind=kind, imported_by=request.user)
        qs = qs.filter(batch_key=batch.file_hash)
    return qs


def deleted_view(request):
    value = request.query_params.get("deleted", "false")
    if value not in {"true", "false"}:
        raise ValidationError("已删除筛选只能为true或false。")
    return value == "true"


class RegistrationView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    kind = ""
    read_permission_code = ""
    write_permission_code = ""
    operation = ""

    def get(self, request, pk=None, evidence_id=None):
        if self.operation == "imports":
            # A batch can contain multiple stores. Re-check today's import scope for each result.
            stores = filter_sales_queryset(request.user, self.read_permission_code, StoreMaster.objects.filter(tenant=request.user.tenant),
                {"store_ids": "id", "platforms": "platform__platform_type", "regions": "country_code"},
                resource_code="finance.gcash" if self.kind == "gcash" else "sales_management.sales")
            allowed_stores = set(stores.values_list("id", flat=True))
            batches = RegistrationImportBatch.objects.filter(tenant=request.user.tenant, kind=self.kind, imported_by=request.user).order_by("-id")
            page, size = _pagination(request)
            current_batches = list(batches[(page - 1) * size:page * size])
            current_ids = {result["id"] for batch in current_batches for result in batch.results if result.get("id")}
            visible_records = dict(scoped(request.user, self.kind, "import", include_deleted=True).filter(pk__in=current_ids).values_list("id", "deleted_at"))
            allowed_ids = set(visible_records)
            results = []
            for batch in current_batches:
                entries = []
                for result in batch.results:
                    if result.get("id") and result["id"] not in allowed_ids:
                        continue
                    if result.get("store_id") and result["store_id"] not in allowed_stores:
                        continue
                    entries.append({**{key: value for key, value in result.items() if key not in {"payload", "snapshot"}},
                                    "deleted": bool(visible_records.get(result.get("id")))})
                results.append({"id": batch.pk, "file_name": batch.file_name, "attachment_name": batch.attachment_name,
                                "imported_by": request.user.username, "created_at": batch.created_at.isoformat(), "results": entries})
            return success_response({"count": batches.count(), "results": results})
        if self.operation == "template":
            return FileResponse(registration_template(self.kind),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, filename=f"{self.kind}-template.xlsx")
        if self.operation == "export":
            qs = scoped(request.user, self.kind, "export", include_deleted=True).filter(deleted_at__isnull=not deleted_view(request))
            qs = filtered_registrations(qs, request, self.kind).select_related("order", "store", "requested_by", "deleted_by")
            if qs.count() > 5000:
                raise ValidationError("单次导出最多5000条，请按店铺或状态缩小范围。")
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="registrations.csv"'
            response.write("\ufeff")
            writer = csv.writer(response)
            extra_headers = {"exchange": ["变化类型", "原SKU", "减少数量", "新SKU", "增加数量", "原因", "备注"],
                             "promotion": ["推广服务费", "服务费币种", "兑换汇率", "汇率日期", "汇率来源", "备注"],
                             "gcash": ["登记类型", "付款日期", "备注"]}[self.kind]
            writer.writerow(["登记编号", "店铺编码", "订单号", "状态", "币种", "登记金额", "登记成本", "创建时间", "删除时间", "删除人", "删除原因", *extra_headers])
            sku_ids = set()
            if self.kind == "exchange":
                for payload in qs.values_list("payload", flat=True):
                    for change in payload.get("changes", []):
                        sku_ids.update(change[key] for key in ("old_sku_id", "new_sku_id") if change.get(key))
            sku_codes = dict(ProductSKU.objects.filter(tenant=request.user.tenant, pk__in=sku_ids).values_list("id", "sku_code"))
            for row in qs.order_by("id"):
                payload = dict(row.payload)
                if self.kind == "gcash":
                    payload["paid_at"] = gcash_payment_date(payload["paid_at"])
                    payload["note"] = gcash_remark(payload.pop("reason", ""), payload.get("note", ""))
                values = [row.pk, row.store.code, row.order.external_order_id if row.order_id else "", row.status,
                          payload.get("currency", ""), payload.get("amount", payload.get("order_amount", "")), payload.get("cost", ""), row.created_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
                          row.deleted_at.isoformat() if row.deleted_at else "", row.deleted_by.username if row.deleted_by_id else "", row.delete_reason]
                if self.kind == "exchange":
                    extras = [[{"add": "增加", "reduce": "减少", "replace": "替换"}.get(change.get("action"), ""),
                               sku_codes.get(change.get("old_sku_id"), ""), change.get("reduce_quantity", ""),
                               sku_codes.get(change.get("new_sku_id"), ""), change.get("add_quantity", ""), payload.get("reason", ""), payload.get("note", "")]
                              for change in payload.get("changes", [])]
                else:
                    keys = ("fee_amount", "fee_currency", "exchange_rate", "rate_date", "rate_source", "note") if self.kind == "promotion" else ("type", "paid_at", "note")
                    extras = [[payload.get(key, "") for key in keys]]
                for extra in extras or [[""] * len(extra_headers)]:
                    writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in [*values, *extra]])
            response["Cache-Control"] = "private, no-store"
            return response
        if self.operation == "options":
            stores = filter_sales_queryset(request.user, self.read_permission_code, StoreMaster.objects.filter(tenant=request.user.tenant),
                                           {"store_ids": "id", "platforms": "platform__platform_type", "regions": "country_code"},
                                           resource_code="finance.gcash" if self.kind == "gcash" else "sales_management.sales")
            if request.query_params.get("store_search"):
                stores = stores.filter(code__icontains=request.query_params["store_search"])
            data = {"stores": list(stores.order_by("code").values("id", "code", "name", "currency")[:100]), "order": None, "skus": []}
            data["historical_exchange_supported"] = self.kind == "exchange"
            if request.query_params.get("store_id"):
                store = store_for(request.user, self.kind, "view", request.query_params["store_id"])
                if request.query_params.get("order_number"):
                    order = get_object_or_404(SalesOrder, tenant=request.user.tenant, store=store, external_order_id=request.query_params["order_number"])
                    original = {}
                    for item in order.items.all():
                        if item.internal_sku_id:
                            original[item.internal_sku_id] = original.get(item.internal_sku_id, 0) + item.quantity
                    pending = PendingOrderDetail.objects.filter(order=order).first()
                    data["order"] = {"id": order.pk, "number": order.external_order_id, "currency": order.currency,
                                     "source_order_amount": str(order.order_total_amount), "status": order.normalized_status,
                                     "original": [{"sku_id": k, "quantity": v} for k, v in original.items()],
                                     "pending": pending.lines if pending else [{"sku_id": k, "quantity": v} for k, v in original.items()]}
                    labels = {sku.pk: sku for sku in ProductSKU.objects.filter(tenant=request.user.tenant, pk__in=set(original) | {line["sku_id"] for line in data["order"]["pending"]})}
                    for key in ("original", "pending"):
                        data["order"][key] = [{**line, "sku_code": labels[line["sku_id"]].sku_code if line["sku_id"] in labels else "",
                                               "product_name": labels[line["sku_id"]].product_name if line["sku_id"] in labels else ""} for line in data["order"][key]]
                    blockers = []
                    if order.normalized_status not in {"pending", "confirmed"} or order.cancelled_at_utc:
                        blockers.append("订单已取消、失效或不再待发货。")
                    if (pending and pending.outbound_reference) or ShipmentRecord.objects.filter(tenant=request.user.tenant, store=store, sales_order=order).exists():
                        blockers.append("订单已有出库／发运记录。")
                    if not original or order.items.filter(internal_sku=None).exists():
                        blockers.append("订单存在未映射商品或没有可调整商品。")
                    active = OrderRegistration.objects.filter(tenant=request.user.tenant, active_exchange_order=order).first()
                    if active:
                        blockers.append(f"已有处理中换货登记 #{active.pk}，请先处理原登记。")
                    data["order"]["adjustment_blockers"] = blockers
                ids = set(MarketplaceProductMapping.objects.filter(tenant=request.user.tenant, store_mapping__store=store, status="mapped").exclude(sku=None).values_list("sku_id", flat=True))
                if data["order"]:
                    ids.update(line["sku_id"] for line in data["order"]["pending"])
                skus = ProductSKU.objects.filter(tenant=request.user.tenant, pk__in=ids, is_active=True)
                if request.query_params.get("sku_search"):
                    skus = skus.filter(sku_code__icontains=request.query_params["sku_search"])
                data["skus"] = list(skus.order_by("sku_code").values("id", "sku_code", "product_name")[:100])
            return success_response(data)
        action = "sensitive" if evidence_id and self.kind == "gcash" else "view"
        qs = scoped(request.user, self.kind, action, include_deleted=True).select_related("order", "store", "requested_by", "deleted_by")
        if pk:
            row = get_object_or_404(qs, pk=pk)
            if evidence_id:
                evidence = get_object_or_404(RegistrationEvidence, pk=evidence_id, registration=row)
                response = FileResponse(io.BytesIO(bytes(evidence.content)), content_type=evidence.media_type, as_attachment=True, filename=evidence.name)
                response["Cache-Control"] = "private, no-store"
                response["X-Content-Type-Options"] = "nosniff"
                return response
            return success_response(representation(row, request.user))
        if not request.query_params.get("request_key"):
            qs = qs.filter(deleted_at__isnull=not deleted_view(request))
        qs = filtered_registrations(qs, request, self.kind)
        summary = {row["status"]: row["total"] for row in qs.values("status").annotate(total=Count("id"))}
        page, size = _pagination(request)
        return success_response({"count": sum(summary.values()), "summary": summary, "results": [representation(row, request.user) for row in qs.order_by("-id")[(page - 1) * size:page * size]]})

    def post(self, request, pk=None):
        if self.operation in {"import-preview", "import-confirm"}:
            return success_response(run_import(request.user, self.kind, request.FILES.get("file"), request.FILES.get("attachments"),
                                               confirm=self.operation == "import-confirm", expected_hash=request.data.get("file_hash", ""),
                                               valid_only=request.data.get("valid_only") == "true",
                                               backfill=request.data.get("backfill", "false") == "true",
                                               offset=request.data.get("offset", 0), limit=request.data.get("limit"),
                                               historical=request.data.get("historical", "false") == "true"))
        if self.operation in {"batch-submit", "batch-delete"}:
            from rest_framework.exceptions import ValidationError, APIException
            ids = request.data.get("ids")
            if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(type(pk) is not int or pk <= 0 for pk in ids):
                raise ValidationError("请提供1至100个登记编号。")
            results = []
            versions = request.data.get("versions", {})
            if not isinstance(versions, dict) or any(type(versions.get(str(pk))) is not int for pk in ids):
                raise ValidationError("每张登记必须提供当前版本号。")
            note = request.data.get("note", "")
            if self.operation == "batch-delete" and (not isinstance(note, str) or not note.strip() or len(note) > 500):
                raise ValidationError("批量删除必须填写不超过500字符的删除原因。")
            for row_id in dict.fromkeys(ids):
                try:
                    row = set_registration_deleted(request.user, self.kind, row_id, versions[str(row_id)], note) if self.operation == "batch-delete" else registration_action(request.user, self.kind, row_id, "submit", expected_version=versions[str(row_id)])
                    results.append({"id": row_id, "success": True, "status": row.status})
                except APIException as exc:
                    results.append({"id": row_id, "success": False, "error": str(exc.detail)})
            return success_response({"results": results})
        if pk:
            if self.operation in {"delete", "restore"}:
                row = set_registration_deleted(request.user, self.kind, pk, request.data.get("version"), request.data.get("note", ""), restore=self.operation == "restore")
            elif self.operation == "evidence":
                upload_evidence(request.user, self.kind, pk, request.FILES.get("file"))
                row = get_object_or_404(scoped(request.user, self.kind, "edit"), pk=pk)
            else:
                from rest_framework.exceptions import ValidationError
                version = request.data.get("version")
                if type(version) is not int or version <= 0:
                    raise ValidationError("操作必须提供当前登记版本号。")
                row = registration_action(request.user, self.kind, pk, self.operation, request.data.get("note", ""), expected_version=version)
            return success_response(representation(row, request.user))
        row, created = create_registration(request.user, self.kind, request.data.get("store_id"), request.data.get("order_id"),
                                           request.data.get("payload"), request.data.get("idempotency_key"),
                                           historical=request.data.get("historical", False))
        return success_response(representation(row, request.user), status=201 if created else 200)

    def patch(self, request, pk):
        row = edit_registration(request.user, self.kind, pk, request.data.get("payload", {}), request.data.get("version"), request.data.get("reason", ""))
        return success_response(representation(row, request.user))
