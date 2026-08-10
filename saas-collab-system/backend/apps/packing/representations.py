from collections import defaultdict


STANDARD_RULE_KEYS = (
    "empty_box_forbidden",
    "exact_completion_required",
    "mixed_box_label_items_required",
    "single_order_single_sku_recommended",
)


def _datetime(value):
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _decimal(value):
    return None if value is None else format(value, "f")


def standard_data(standard):
    rules = standard.rules if isinstance(standard.rules, dict) else {}
    return {
        "code": standard.code,
        "version": standard.version,
        "title": standard.title,
        "rules": {key: bool(rules.get(key, False)) for key in STANDARD_RULE_KEYS},
    }


def _orders(batch):
    return [
        link.order
        for link in sorted(batch.batch_orders.all(), key=lambda item: item.order_id)
    ]


def _boxes(batch):
    return sorted(batch.boxes.all(), key=lambda item: item.sequence)


def _box_data(box):
    items = sorted(box.items.all(), key=lambda item: item.id)
    return {
        "id": box.id,
        "box_no": box.box_no,
        "sequence": box.sequence,
        "weight": _decimal(box.weight),
        "volume": _decimal(box.volume),
        "note": box.note or "",
        "items": [
            {
                "order_line_id": item.order_line_id,
                "order_no": item.order_no_snapshot,
                "sku_code": item.sku_code_snapshot,
                "product_name": item.product_name_snapshot,
                "quantity": item.quantity,
            }
            for item in items
        ],
        "created_at": _datetime(box.created_at),
        "updated_at": _datetime(box.updated_at),
    }


def batch_summary_data(batch):
    orders = _orders(batch)
    boxes = _boxes(batch)
    total_quantity = sum(line.quantity for order in orders for line in order.lines.all())
    packed_quantity = sum(
        item.quantity for box in boxes for item in box.items.all()
    )
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "supplier": {
            "id": batch.supplier_id,
            "code": batch.supplier.code,
            "name": batch.supplier.name,
        },
        "status": batch.status,
        "version": batch.version,
        "standard": {
            "code": batch.standard_version.code,
            "version": batch.standard_version.version,
            "title": batch.standard_version.title,
        },
        "order_count": len(orders),
        "box_count": len(boxes),
        "packed_quantity": packed_quantity,
        "total_quantity": total_quantity,
        "completed_at": _datetime(batch.completed_at),
        "created_at": _datetime(batch.created_at),
        "updated_at": _datetime(batch.updated_at),
    }


def batch_detail_data(batch, *, internal):
    data = batch_summary_data(batch)
    orders = _orders(batch)
    boxes = _boxes(batch)
    packed = defaultdict(int)
    for box in boxes:
        for item in box.items.all():
            packed[item.order_line_id] += item.quantity
    remaining = []
    for order in orders:
        for line in sorted(order.lines.all(), key=lambda item: item.id):
            packed_quantity = packed[line.id]
            remaining.append(
                {
                    "order_line_id": line.id,
                    "order_no": order.order_no,
                    "sku_code": line.sku_code_snapshot,
                    "product_name": line.product_name_snapshot,
                    "ordered_quantity": line.quantity,
                    "packed_quantity": packed_quantity,
                    "remaining_quantity": line.quantity - packed_quantity,
                }
            )
    data.update(
        {
            "note": batch.note or "",
            "orders": [{"id": order.id, "order_no": order.order_no} for order in orders],
            "boxes": [_box_data(box) for box in boxes],
            "remaining": remaining,
        }
    )
    if internal:
        data["created_by"] = {
            "id": batch.created_by_id,
            "display_name": batch.created_by.username,
        }
    return data


def change_request_data(change, *, internal):
    data = {
        "id": change.id,
        "batch_id": change.batch_id,
        "status": change.status,
        "expected_version": change.expected_version,
        "reason": change.reason,
        "proposed_boxes": change.proposed_boxes,
        "review_note": change.review_note or "",
        "applied_version": change.applied_version,
        "reviewed_at": _datetime(change.reviewed_at),
        "created_at": _datetime(change.created_at),
    }
    if internal:
        data["submitted_by"] = {
            "id": change.submitted_by_id,
            "display_name": change.submitted_by.username,
        }
        data["reviewed_by"] = (
            {
                "id": change.reviewed_by_id,
                "display_name": change.reviewed_by.username,
            }
            if change.reviewed_by_id
            else None
        )
    return data
