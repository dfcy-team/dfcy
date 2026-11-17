"""Pure country-level inventory/listing risk classification.

Call once per product and country. Inputs are current inventory evidence and
listing states (``on``, ``off`` or ``unknown``); this module does no I/O.
"""


def classify_country_risk(
    *,
    on_hand_qty=None,
    available_qty=None,
    in_transit_qty=0,
    pending_putaway_qty=0,
    inventory_known=True,
    inventory_type="physical",
    listing_states=(),
    has_mapping=True,
    deadstock_threshold_days=None,
    stock_age_days=None,
):
    """Return stable risk code, Chinese label, reasons and replenishment flag.

    ``listing_states`` may contain ``on``, ``off`` and/or ``unknown``. States
    are scoped to a single country by the caller. Missing inventory is not zero.
    """
    raw_states = tuple(str(s).lower() for s in (listing_states or ()))
    states = tuple(s if s in {"on", "off"} else "unknown" for s in raw_states)
    reasons = []
    result = {"replenishment_manual_check": False,
              "deadstock": False, "deadstock_days": None}

    if inventory_type == "virtual":
        result.update(code="virtual_inventory", label="虚拟库存单独管理",
                      replenishment_manual_check=True)
        reasons.append("库存类型标记为虚拟")
    elif not inventory_known or available_qty is None or (available_qty == 0 and on_hand_qty is None):
        result.update(code="inventory_unknown", label="库存待核实",
                      replenishment_manual_check=True)
        reasons.append("没有有效库存证据，不能按零库存处理")
    elif available_qty > 0:
        if "on" in states:
            result.update(code="in_stock_listed", label="有库存且有在售商品")
        elif "unknown" in states:
            result.update(code="listing_pending", label="有库存，上架状态待核实",
                          replenishment_manual_check=True)
            reasons.append("存在无法确认上下架状态的平台关联")
        else:
            result.update(code="in_stock_unlisted", label="有库存未上架",
                          replenishment_manual_check=True)
            if not has_mapping:
                reasons.append("没有对应的平台商品映射")
            elif "off" in states:
                reasons.append("关联的平台商品均已下架")
            else:
                reasons.append("没有确认在售的平台商品")
    elif on_hand_qty is not None and on_hand_qty > 0:
        result.update(code="stock_unavailable", label="有在库但当前无可用库存",
                      replenishment_manual_check=True)
        reasons.append("在库数量大于零，但可用数量为零")
    elif in_transit_qty > 0 or pending_putaway_qty > 0:
        result.update(code="incoming_stock", label="仅在途或待仓库上架",
                      replenishment_manual_check=True)
        if in_transit_qty > 0:
            reasons.append("存在在途库存")
        if pending_putaway_qty > 0:
            reasons.append("存在仓库待上架库存")
    else:
        result.update(code="zero_stock_snapshot", label="快照库存为零")

    if (deadstock_threshold_days is not None and stock_age_days is not None
            and deadstock_threshold_days >= 0 and stock_age_days >= deadstock_threshold_days
            and available_qty is not None and available_qty > 0
            and inventory_type != "virtual"):
        result["deadstock"] = True
        result["deadstock_days"] = stock_age_days
        reasons.append("库存库龄达到滞销预警阈值")
    if "on" not in states:
        result["replenishment_manual_check"] = True
        if not reasons:
            reasons.append("缺少对应国家明确在售证据，补货需人工核查")
    result["reasons"] = reasons
    return result
