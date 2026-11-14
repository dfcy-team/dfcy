"""Flash-sale rules; identifiers and prices remain strings at the API boundary."""
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


TERMINAL = {"succeeded", "failed", "stopped", "missed"}
BACKOFF = (30, 60, 120, 300)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def integer(value, label, minimum=1, maximum=999999):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label}须为 {minimum}～{maximum} 的整数。")
    return value


def identifier(value):
    value = str(value)
    if not value.isascii() or not value.isdecimal() or len(value) > 30:
        raise ValidationError("平台编号无效。")
    return value


def price(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("活动价格无效。") from None
    if not result.is_finite() or not 0 < result <= Decimal("999999999"):
        raise ValidationError("活动价格须大于 0 且不超过 999999999。")
    return format(result, "f")


def validate_items(rows, source=None):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValidationError("请选择 1～10000 个规格。")
    available = {(r["item_id"], r["model_id"]) for r in source} if source is not None else None
    result, seen, limits = [], set(), {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"item_id", "model_id", "price", "stock", "purchase_limit", "participate"}:
            raise ValidationError("商品编辑字段无效。")
        if row.get("participate") is False:
            continue
        item, model = identifier(row.get("item_id")), identifier(row.get("model_id", "0"))
        if (item, model) in seen or (available is not None and (item, model) not in available):
            raise ValidationError("重复规格或规格不属于所选来源活动。")
        seen.add((item, model))
        limit = integer(row.get("purchase_limit", 0), "购买限额", minimum=0)
        if item in limits and limits[item] != limit:
            raise ValidationError("同一商品的各规格购买限额须一致。")
        limits[item] = limit
        result.append({"item_id": item, "model_id": model, "price": price(row.get("price")),
                       "stock": integer(row.get("stock"), "活动库存"), "purchase_limit": limit})
    if not result:
        raise ValidationError("至少选择一个参加规格。")
    return result


def item_bodies(rows, *, update=False):
    groups = defaultdict(list)
    for row in rows:
        groups[row["item_id"]].append(row)
    bodies = []
    for item, values in groups.items():
        body = {"item_id": int(item)}
        if not update:
            body["purchase_limit"] = values[0]["purchase_limit"]
        if values[0]["model_id"] == "0":
            body.update(item_input_promo_price=float(Decimal(values[0]["price"])), item_stock=values[0]["stock"])
            if update:
                body["item_status"] = 1
        else:
            body["models"] = [{"model_id": int(row["model_id"]), "input_promo_price": float(Decimal(row["price"])),
                               "stock": row["stock"], **({"status": 1} if update else {})} for row in values]
        bodies.append(body)
    return bodies


def normalize_items(items, models):
    result = []
    for item in items:
        variants = [row for row in models if str(row["item_id"]) == str(item["item_id"])]
        for row in variants or [item]:
            result.append({"item_id": identifier(item["item_id"]), "model_id": identifier(row.get("model_id", 0)),
                           "price": str(row.get("input_promotion_price") or ""),
                           "stock": row.get("campaign_stock"), "available_stock": row.get("stock"),
                           "purchase_limit": row.get("purchase_limit", item.get("purchase_limit", 0)),
                           "status": row.get("status", row.get("item_status")),
                           "name": str(item.get("item_name") or "")[:240],
                           "image": item["image"] if isinstance(item.get("image"), str) and item["image"].startswith("https://") else "",
                           "model_name": str(row.get("model_name") or "")[:240],
                           "original_price": row.get("original_price"),
                           "reject_reason": str(row.get("reject_reason") or "")[:500]})
    return result


def reconcile(planned, actual, rejections):
    actual = {(row["item_id"], row["model_id"]): row for row in actual}
    rejected = {(str(row["item_id"]), str(row.get("model_id", 0))): row for row in rejections}
    results = []
    for row in planned:
        key = row["item_id"], row["model_id"]
        read = actual.get(key)
        state, reason = "unknown", "平台结果尚未确认，继续回读"
        if read and read.get("status") == 1:
            try:
                matches = Decimal(read["price"]) == Decimal(row["price"]) and read["stock"] == row["stock"]
            except (InvalidOperation, TypeError, KeyError):
                matches = False
            state, reason = ("enabled", "已启用") if matches else ("mismatch", "平台价格或库存与提交值不一致")
        elif key in rejected:
            state, reason = "rejected", rejected[key].get("reason", "平台拒绝参加")
        elif read and read.get("status") == 0:
            state, reason = "rejected", "平台未启用该规格：" + (read.get("reject_reason") or "未返回原因")
        results.append({**row, "state": state, "reason": reason, "readback": read})
    return results


def retry_delay(attempt, retry_after=0):
    return max(BACKOFF[min(attempt, len(BACKOFF) - 1)], retry_after or 0)
