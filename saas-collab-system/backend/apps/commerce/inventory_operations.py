"""Conservative operating labels derived from existing, permission-scoped facts.

Calendar-day sales are observations, not an estimate of demand on in-stock days.
No database access or unverified availability/arrival history is introduced here.
"""
from decimal import Decimal, InvalidOperation


def _number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def operating_assessment(row, *, window_days=30, target_days=60):
    result = {
        'sales_status': 'unknown', 'sales_label': '销售待判断',
        'inventory_status': 'unknown', 'inventory_label': '库存待核查',
        'action': '补齐数据后重新校验', 'evidence': [],
        'observation_basis': 'calendar_days', 'availability_history_complete': False,
        'policy_version': 'inventory-operations-v1',
        'low_coverage_days': 7, 'target_days': target_days,
        'arrival_prediction_status': 'unavailable',
    }
    evidence = result['evidence']
    evidence.append(f'日均销量按最近 {window_days} 个自然日观察；尚无完整历史可售天数，不判定畅销或滞销。')
    if row.get('mapped_only'):
        evidence.append('仅统计本商品最新有效映射的仓库库存、已映射订单及已验证组合组件；其他未映射记录不阻断观察。')
        if not row.get('inventory_type'):
            evidence.append('库存类型未填写；按用户选择继续纳入，类型仍待完善。')
        units = _number(row.get('mapped_sales_units'))
        available = _number(row.get('available_stock'))
        if row.get('unmapped_inventory_excluded'):
            evidence.append('仓内其他未映射库存已排除，当前不是全仓完整库存。')
        if row.get('unmapped_sales_excluded') or row.get('unknown_bundle_demand_excluded'):
            evidence.append('未映射订单和无法验证的组合需求未计入，已知成交不是完整需求。')
        if units is not None and units > 0:
            result.update(sales_status='observed_sales', sales_label='已映射有成交')
            evidence.append(f'已映射成交及已验证组件消耗 {units} 件。')
        elif row.get('mapped_sales_complete'):
            result.update(sales_status='no_sales', sales_label=f'近 {window_days} 天已映射零销量')
        else:
            result['sales_label'] = '未见已映射成交 · 覆盖待核实'
        if not row.get('inventory_complete') or available is None:
            evidence.append('本商品映射库存自身缺字段、过期或来源异常，需单独核查。')
        elif available <= 0:
            result.update(inventory_status='out', inventory_label='已映射库存无可售', action='核查本商品库存及可调拨货源')
        elif units is not None and units > 0:
            coverage = available * window_days / units
            result['observed_coverage_days'] = str(coverage.quantize(Decimal('0.01')))
            if not row.get('mapped_sales_complete'):
                result.update(inventory_status='observed', inventory_label='已映射覆盖参考', action='参考已映射成交核对库存；完整需求待补齐')
            elif available * window_days < units * 7:
                result.update(inventory_status='low', inventory_label='已映射现货低覆盖', action='核对到货日期，优先调拨或催货')
            elif available * window_days > units * target_days:
                result.update(inventory_status='over', inventory_label='已映射现货超目标', action='复核在途与需求，评估暂缓采购')
            else:
                result.update(inventory_status='sufficient', inventory_label='已映射覆盖在目标内', action='持续观察销售及到货变化')
            evidence.append(f'已映射可售 {available} 件，观察覆盖 {coverage:.2f} 天；不计在途。')
        else:
            result.update(inventory_status='observed', inventory_label='已映射库存可观察', action='核对上架和销售采集，零观察不判滞销')
        evidence.append('该观察不直接生成采购或预警；完整需求仍按原复核流程校验。')
        return result
    issues = set(row.get('issues') or []) | set(row.get('blocking_issues') or [])
    sales = next((item for item in row.get('sales_windows', []) if item.get('days') == window_days), {})
    sales_blockers = {'no_sales_facts', 'unmapped_sales_lines', 'collection_coverage_unproven',
                      'invalid_store_timezone', 'unfinished_store_day', 'no_authorized_sales_store',
                      'bundle_composition_unverified'}
    units = _number(sales.get('units'))
    daily = _number(row.get('daily_sales'))
    verified_sales = sales.get('coverage_complete') is True and not issues.intersection(sales_blockers)
    if verified_sales and units is not None and units >= 0 and daily is not None and daily >= 0:
        daily = units / Decimal(window_days)
        if units == 0:
            result.update(sales_status='no_sales', sales_label=f'近 {window_days} 天零销量')
            evidence.append('零销量不等于有货无销；需核实上架状态与历史断货。')
        else:
            result.update(sales_status='observed_sales', sales_label='有成交 · 观察中')
            evidence.append(f'窗口有效成交 {units} 件，观察日均 {daily} 件。')
    else:
        verified_sales = False
        evidence.append('销售采集、映射或窗口完整性未通过核验。')
    available = _number(row.get('available_stock'))
    if row.get('inventory_complete') is not True or available is None:
        evidence.append('当前可售库存来源不完整或已过期。')
        return result
    evidence.append(f'当前可售 {available} 件；不重复扣除占用，不加入在途。')
    if available <= 0:
        result.update(inventory_status='out', inventory_label='当前无可售', action='核查库存与可调拨货源')
    elif not verified_sales:
        return result
    elif daily == 0:
        result.update(action='核对链接、历史断货与定价')
    else:
        coverage = available / daily
        result['observed_coverage_days'] = str(coverage.quantize(Decimal('0.01')))
        if available * window_days < units * 7:
            result.update(inventory_status='low', inventory_label='现货低覆盖', action='核对到货日期，优先调拨或催货')
        elif available * window_days > units * target_days:
            result.update(inventory_status='over', inventory_label='现货超目标', action='复核在途与需求，评估暂缓采购')
        else:
            result.update(inventory_status='sufficient', inventory_label='现货覆盖在目标内', action='持续观察销售及到货变化')
        evidence.append(f'现货观察覆盖 {coverage:.2f} 天；低覆盖阈值 7 天，目标上限 {target_days} 天。')
    evidence.append('尚未完成逐批可上架日期预测；当前覆盖不能证明到货前不会断货。')
    if issues.intersection({'unknown_eta', 'overdue_eta', 'wms_receipt_overlap_unresolved',
                            'warehouse_supply_scope_incomplete', 'unassigned_warehouse_supply'}):
        evidence.append('供应日期或收货关联待核查，不用在途抵消现货风险。')
    return result
