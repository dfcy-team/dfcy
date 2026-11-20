"""Fail-closed proof for TikTok refund lines whose per-unit quantity is omitted."""

from copy import deepcopy

from rest_framework.exceptions import ValidationError


def confirm_missing_unit_quantities(items, *, tenant_id, store_id, order_id):
    """Return copied items with quantity=1 only when exact order-line facts prove it."""
    result = deepcopy(items)
    missing = [item for item in result if isinstance(item, dict)
               and item.get("quantity") in (None, "")
               and item.get("return_quantity") in (None, "")]
    if not missing:
        return result, []
    return_ids = [str(item.get("return_line_item_id") or "").strip() for item in missing]
    line_ids = [str(item.get("order_line_item_id") or "").strip() for item in missing]
    all_return_ids = [str(item.get("return_line_item_id") or item.get("id") or "").strip()
                      for item in result if isinstance(item, dict)]
    all_line_ids = [str(item.get("order_line_item_id") or item.get("sub_order_line_item_id") or "").strip()
                    for item in result if isinstance(item, dict)]
    if (not all(return_ids) or not all(line_ids) or len(set(all_return_ids)) != len(all_return_ids)
            or len(set(all_line_ids)) != len(all_line_ids) or not str(order_id or "").strip()):
        raise ValidationError("TK_RETURN_QUANTITY_UNCONFIRMED：平台退货数量待核对，未按默认数量登记。")

    from apps.commerce.models import SalesOrderItem

    expected_variants = [str(item.get("sku_id") or "").strip() for item in missing]
    if not all(expected_variants):
        raise ValidationError("TK_RETURN_QUANTITY_UNCONFIRMED：平台退货数量待核对，未按默认数量登记。")
    rows = SalesOrderItem.objects.filter(
        sales_order__tenant_id=tenant_id,
        sales_order__store_id=store_id,
        sales_order__external_order_id=str(order_id),
        external_line_id__in=set(line_ids),
    ).values_list("external_line_id", "quantity", "platform_variant_id")
    matches = {}
    for line_id, quantity, variant_id in rows:
        matches.setdefault(line_id, []).append((quantity, str(variant_id or "")))
    proofs = []
    for item, return_id, line_id, variant_id in zip(missing, return_ids, line_ids, expected_variants):
        facts = matches.get(line_id, [])
        if len(facts) != 1 or facts[0][0] != 1 or facts[0][1] != variant_id:
            raise ValidationError("TK_RETURN_QUANTITY_UNCONFIRMED：平台退货数量待核对，未按默认数量登记。")
        item["quantity"] = 1
        proof = {"return_line_item_id": return_id, "order_line_item_id": line_id,
                 "quantity": 1, "source": "matching_sales_order_item"}
        item["quantity_confirmation"] = proof
        proofs.append(proof)
    return result, proofs
