"""Parse the BigSeller order/SKU export without touching the database."""

import csv
import re
from datetime import datetime, timedelta, timezone
from io import StringIO

from rest_framework.exceptions import ValidationError

from apps.masterdata.platform_catalog import normalize_platform_code

from .scopes import market_countries


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
MAX_QUANTITY = 2_147_483_647
SOURCE_TIME_ZONE = "Asia/Shanghai"
CSV_TIME_ZONE = timezone(timedelta(hours=8))
CSV_COLUMNS = {
    "订单号": "order_no",
    "平台": "platform",
    "BigSeller店铺": "big_seller_store",
    "平台店铺": "platform_store",
    "国家": "country",
    "产品ID": "external_product_id",
    "商品SKU": "product_sku",
    "店铺SKU": "shop_sku",
    "数量": "quantity",
    "发货仓库": "warehouse_name",
    "下单时间": "sample_sent_at",
    "发货时间": "shipped_at",
    "订单状态": "source_status",
    "取消时间": "cancelled_at",
    "是否出库": "is_outbound",
}
ORDER_FIELDS = (
    "platform", "big_seller_store", "platform_store", "country_code",
    "warehouse_name", "sample_sent_at", "shipped_at", "source_status",
    "cancelled_at", "is_outbound",
)
SHIPPED_STATUSES = {"已交运", "已发货"}
PENDING_STATUSES = {"待处理", "待打单", "待发货", "待配货", "待拣货", "待包装", "待交运"}
DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?(?:\+08:00)?")
SCIENTIFIC_ID = re.compile(r"[0-9]+(?:\.[0-9]+)?[eE][+-]?[0-9]+")


def _timestamp(value, *, required=False):
    if not value and not required:
        return None
    if not DATE_TIME.fullmatch(value):
        raise ValueError("日期时间须为北京时间 YYYY-MM-DD HH:MM[:SS]。")
    result = datetime.fromisoformat(value)
    if not 1001 <= result.year <= 9998:
        raise ValueError("日期时间超出可导入范围。")
    return (result if result.tzinfo else result.replace(tzinfo=CSV_TIME_ZONE)).astimezone(CSV_TIME_ZONE)


def _fields(row):
    if any(any(ord(char) < 32 for char in value) for value in row.values()):
        raise ValueError("字段中包含无效的控制字符。")
    for field, limit in {
        "order_no": 120, "platform": 40, "big_seller_store": 160,
        "platform_store": 160, "country": 80, "external_product_id": 120,
        "product_sku": 120, "shop_sku": 120, "warehouse_name": 120,
        "source_status": 40,
    }.items():
        if len(row[field]) > limit:
            raise ValueError(f"{field} 超出长度限制。")
    if not all(row[f] for f in (
        "order_no", "big_seller_store", "platform_store", "country",
        "warehouse_name", "external_product_id",
    )):
        raise ValueError("订单号、店铺、国家、发货仓库和产品 ID 均为必填。")
    if re.search(r"[,，、;；]", row["external_product_id"]):
        raise ValueError("每条 SKU 明细只能有一个产品 ID。")
    if any(SCIENTIFIC_ID.fullmatch(row[key]) for key in ("order_no", "external_product_id")):
        raise ValueError("订单号和产品 ID 须保留原始文本，不能使用科学计数法。")
    if normalize_platform_code(row["platform"]) != "tiktok":
        raise ValueError("此入口目前只支持 TikTok 订单。")
    countries = market_countries(row["country"])
    if len(countries) != 1 or not re.fullmatch(r"[A-Z]{2}", next(iter(countries))):
        raise ValueError("无法识别单一订单国家。")
    sent = _timestamp(row["sample_sent_at"], required=True)
    shipped = _timestamp(row["shipped_at"])
    cancelled = _timestamp(row["cancelled_at"])
    outbound = {"yes": True, "no": False, "是": True, "否": False}.get(row["is_outbound"].casefold())
    if cancelled is not None or row["source_status"] in {"已取消", "取消"}:
        raise ValueError("不支持导入已取消订单。")
    if row["source_status"] in SHIPPED_STATUSES and outbound is True and shipped is not None and shipped >= sent:
        status = "shipped"
    elif row["source_status"] in PENDING_STATUSES and outbound is False and shipped is None:
        status = "pending"
    else:
        raise ValueError("订单状态、出库标记和发货时间不一致，或订单状态不受支持。")
    sku = row["product_sku"] or row["shop_sku"]
    if not sku or not re.fullmatch(r"[0-9]{1,10}", row["quantity"]):
        raise ValueError("每条明细需要 SKU 和正整数数量。")
    quantity = int(row["quantity"])
    if not 1 <= quantity <= MAX_QUANTITY:
        raise ValueError("SKU 数量超出范围。")

    order = {
        **{key: row[key] for key in ("order_no", "big_seller_store", "platform_store", "warehouse_name", "source_status")},
        "platform": "TikTok",
        "country_code": next(iter(countries)),
        "sample_sent_at": sent.isoformat(),
        "shipped_at": shipped.isoformat() if shipped else None,
        "cancelled_at": None,
        "is_outbound": outbound,
        "status": status,
    }
    item = {
        **{key: row[key] for key in ("external_product_id", "product_sku", "shop_sku")},
        "requested_sku": sku,
        "quantity": quantity,
    }
    return order, item


def _decoded(upload):
    if upload.size > MAX_FILE_BYTES:
        raise ValidationError({"file": "CSV 文件不能超过 2 MiB。"})
    content = upload.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValidationError({"file": "CSV 文件不能超过 2 MiB。"})
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError({"file": "仅支持 UTF-8 或 GB18030 编码的 CSV。"})


def parse_order_csv(upload):
    reader = csv.reader(StringIO(_decoded(upload), newline=""), strict=True)
    groups = {}
    row_count = 0
    try:
        header = [value.strip() for value in next(reader, [])]
        if len(header) != len(CSV_COLUMNS) or set(header) != set(CSV_COLUMNS):
            raise ValidationError({"file": "CSV 表头须包含 BigSeller 订单 SKU 导出的全部 15 列。"})
        keys = [CSV_COLUMNS[column] for column in header]
        order_index = keys.index("order_no")
        while True:
            row_number = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if not any(cell.strip() for cell in cells):
                continue
            row_count += 1
            if row_count > MAX_ROWS:
                raise ValidationError({"file": "CSV 最多支持 500 条数据行（含 SKU 明细）。"})
            order_no = cells[order_index].strip() if order_index < len(cells) else ""
            group = groups.setdefault(
                order_no.casefold() if order_no else row_number,
                {"order_no": order_no[:120], "row_numbers": [], "items": [], "errors": []},
            )
            group["row_numbers"].append(row_number)
            try:
                if len(cells) != len(keys):
                    raise ValueError("该行不是 15 列。")
                order, item = _fields(dict(zip(keys, (cell.strip() for cell in cells))))
                if "status" not in group:
                    group.update(order, external_product_id=item["external_product_id"])
                elif any(group[key] != order[key] for key in ORDER_FIELDS):
                    raise ValueError("同一订单的店铺、国家、仓库或状态时间不一致。")
                if item["external_product_id"] != group["external_product_id"]:
                    raise ValueError("同一订单包含多个产品 ID；当前不支持导入此类订单。")
                group["items"].append(item)
            except ValueError as exc:
                group["errors"].append({"row_number": row_number, "code": "invalid_csv_row", "message": str(exc)})
    except csv.Error as exc:
        raise ValidationError({"file": f"CSV 格式不正确，请检查第 {reader.line_num} 行。"}) from exc
    if not row_count:
        raise ValidationError({"file": "CSV 没有订单数据。"})
    for group in groups.values():
        _combine_skus(group)
    return list(groups.values()), row_count


def _combine_skus(group):
    items = {}
    total_quantity = 0
    for item in group["items"]:
        total_quantity += item["quantity"]
        key = item["requested_sku"].casefold()
        prior = items.get(key)
        if prior is None:
            items[key] = item
        elif (
            prior["product_sku"].casefold() != item["product_sku"].casefold()
            or prior["shop_sku"].casefold() != item["shop_sku"].casefold()
        ):
            group["errors"].append({"code": "conflicting_sku", "message": "同一订单中的相同 SKU 对应不同的店铺 SKU。"})
        else:
            prior["quantity"] += item["quantity"]
    if total_quantity > MAX_QUANTITY:
        group["errors"].append({"code": "invalid_quantity", "message": "订单的 SKU 总数量超出范围。"})
    group["items"] = list(items.values())
