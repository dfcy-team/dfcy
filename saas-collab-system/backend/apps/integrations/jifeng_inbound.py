"""Import standard WMS receiving lines through the unified sync runner."""

from datetime import datetime, timedelta, timezone as datetime_timezone

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.commerce.models import InboundRecord

from .adapters import ProductionReadonlyAdapter
from .warehouse_api_contract import operation_for


WMS_CLOCK = datetime_timezone(timedelta(hours=8))
PAGE_SIZE = 100


class JifengInboundAdapter(ProductionReadonlyAdapter):
    def validate_configuration(self, sync_job):
        if not sync_job.warehouse_authorization_id:
            raise ValidationError("Standard inbound sync requires a verified warehouse authorization.")
        super().validate_configuration(sync_job)

    def fetch_page(self, sync_job, cursor_value=None):
        run = self._require_run()
        if cursor_value:
            end_text, page_text = cursor_value.split("|")
            end = datetime.fromisoformat(end_text)
            page_number = int(page_text)
        else:
            end = run.started_at.astimezone(WMS_CLOCK).replace(microsecond=0)
            page_number = 1
        warehouse = self.warehouse_authorization.external_warehouse_code
        endpoint = operation_for("inbound_page").path
        response = self._client()._signed_post(endpoint, {
            "warehouse": warehouse,
            "beginTime": (end - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
            "pageNo": page_number,
            "pageSize": PAGE_SIZE,
        })
        data = response.get("data") if isinstance(response, dict) and response.get("code") == 0 else None
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise ValidationError("Jifeng inbound query did not return a valid page.")
        rows = data["rows"]
        total_pages = data.get("totalPage")
        if (type(total_pages) is not int or total_pages < 0 or data.get("pageNo") != page_number
                or len(rows) > PAGE_SIZE or (not rows and page_number < total_pages)):
            raise ValidationError("Jifeng inbound pagination metadata is inconsistent.")
        records = []
        for order in rows:
            if order.get("warehouseCode") != warehouse or not order.get("inboundNo"):
                raise ValidationError("Jifeng inbound response contains an unexpected warehouse or missing order ID.")
            lines = {}
            for line in order.get("skuList") or []:
                sku = str(line.get("sku") or "").strip()
                planned, received = line.get("count"), line.get("receiveCount")
                if received is None and order.get("receiveStatus") in (0, 1):
                    received = 0
                if not sku or any(type(value) is not int or value < 0 for value in (planned, received)):
                    raise ValidationError("Jifeng inbound response contains invalid SKU quantities.")
                totals = lines.setdefault(sku, [0, 0])
                totals[0] += planned
                totals[1] += received
            for sku, (planned, received) in lines.items():
                records.append({
                    "external_inbound_id": order["inboundNo"],
                    "external_line_id": sku,
                    "source_sku": sku,
                    "planned_quantity": planned,
                    "received_quantity": received,
                    "status": str(order["status"]),
                    "received_at_utc": self._provider_time(order.get("receiveLastTime")),
                    "updated_at_utc": self._provider_time(
                        order.get("finishTime") or order.get("putawayLastTime")
                        or order.get("receiveLastTime") or order.get("signTime")
                    ),
                })
        return {
            "records": records,
            "raw_responses": [{"endpoint": endpoint, "payload": response}],
            "next_cursor": f"{end.isoformat()}|{page_number + 1}" if page_number < total_pages else "",
        }

    @staticmethod
    def _provider_time(value):
        if not value:
            return None
        timestamp = datetime.fromisoformat(value)
        if timezone.is_naive(timestamp):
            timestamp = timestamp.replace(tzinfo=WMS_CLOCK)
        return timestamp.astimezone(datetime_timezone.utc).isoformat()

    def normalize_record(self, record):
        return record

    def persist_record(self, sync_job, record):
        run = self._require_run()
        warehouse = self.warehouse_authorization.warehouse
        identity = {
            "tenant_id": sync_job.tenant_id,
            "warehouse": warehouse,
            "site_code": warehouse.country_code.upper(),
            "external_inbound_id": record["external_inbound_id"],
            "external_line_id": record["external_line_id"],
        }
        changes = {
            "inbound_type": "standard",
            "source_sku": record["source_sku"],
            "planned_quantity": record["planned_quantity"],
            "received_quantity": record["received_quantity"],
            "status": record["status"],
            "received_at_utc": datetime.fromisoformat(record["received_at_utc"]) if record["received_at_utc"] else None,
        }
        current = InboundRecord.objects.select_for_update().filter(**identity).first()
        if current and all(getattr(current, key) == value for key, value in changes.items()):
            return {"action": "skipped", "idempotency_key": f"{sync_job.pk}:{current.pk}"}
        saved, created = InboundRecord.objects.update_or_create(**identity, defaults={
            **changes,
            "updated_at_utc": datetime.fromisoformat(record["updated_at_utc"]) if record["updated_at_utc"] else run.started_at,
            "source_run": run,
        })
        return {"action": "created" if created else "updated", "idempotency_key": f"{sync_job.pk}:{saved.pk}"}
