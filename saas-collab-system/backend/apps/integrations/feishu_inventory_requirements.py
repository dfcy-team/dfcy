"""Fail-closed inventory-risk content readiness, not a fabricated alert engine."""
from datetime import date, timedelta
from types import SimpleNamespace
from apps.reports.datasets import query_dataset


def inventory_requirements(user, filters, multiplier=10):
    D = date.fromisoformat(filters['date_to'])
    result = {'status': 'not_ready', 'multiplier': multiplier, 'end_date': D.isoformat(), 'alerts': [],
              'actual_risk_evaluation_enabled': False, 'message': '库存风险消息暂不投递；不代表当前没有断货、补货或到仓事项。'}
    sales_status = 'unverified'
    unmapped = None
    try:
        source = query_dataset(SimpleNamespace(user=user), {'dataset':'sales_skus','dimensions':['internal_sku'],
            'metrics':['units_sold','unmapped_count'],'filters':{'date_from':(D-timedelta(days=6)).isoformat(),'date_to':D.isoformat()}}, use_cache=False)
        if source.get('truncated'):
            sales_status = 'truncated'
        elif not source.get('rows'):
            sales_status = 'no_observation'
        else:
            unmapped = sum(r.get('unmapped_count') or 0 for r in source['rows'])
            sales_status = 'unmapped' if unmapped or any(not r.get('internal_sku') for r in source['rows']) else 'mapping_present_coverage_unverified'
    except Exception:
        sales_status = 'unavailable_or_not_authorized'
    result.update(sales_status=sales_status, unmapped_item_rows=unmapped)
    result['alerts'] = [
        {'kind':'stockout','title':'断货提醒','frequency':'每72小时最多一次','formula':f'在库 + 在途 < 近7天总销量 × {multiplier}','status':'not_ready','reason':'需内部SKU销量关联、完整且新鲜的在库/在途、经确认的SKU前缀规则。'},
        {'kind':'replenishment','title':'补货提醒','frequency':'每72小时最多一次','formula':f'在库 + 在途 + 在生产 < 近7天总销量 × {multiplier}','status':'not_ready','reason':'需完整生产和在途余额，避免生产、运输、在库重复计量。'},
        {'kind':'best_child','title':'畅销子SKU补货','frequency':'每72小时最多一次','formula':'每个SKU前缀选择近7天销量最高子SKU，再按该子SKU判断补货','status':'not_ready','reason':'销售明细关联和前缀规则尚需核验；不能直接按字符串截取或使用前缀总库存代替畅销规格库存。'},
        {'kind':'arrival','title':'到仓首次提醒','frequency':'每天检查；每批次首次一次','formula':'真实到仓事件 → 仅列SKU前缀','status':'not_ready','reason':'需接入有权限范围内的真实到仓事件；不以库存增加代替到仓。'},
        {'kind':'uncounted','title':'到仓三天未清点','frequency':'每天检查；满72小时第二次一次','formula':'已到仓且72小时后仍有未清点行 → 仅列未清点SKU前缀','status':'not_ready','reason':'需到仓时间、清点行和确认状态；部分清点只列剩余行。'},
    ]
    return result
