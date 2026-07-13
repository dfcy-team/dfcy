import { successResponse } from './index';

const evidence = {
  sales_trend: '连续 4 周下降（演示）',
  stock_cover_days: 86,
  gross_margin_placeholder: '已脱敏',
  listing_status: 'active',
  supplier_delivery: 'on_time',
  data_quality: 'good'
};

export const mockLifecycleReviews = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '待复盘', value: 14 }, { label: '滞销观察', value: 6 }, { label: '清仓候选', value: 3 }, { label: '高风险确认', value: 2 }
  ],
  items: [
    { review_id: 'DEMO-LIFE-001', spu_code: 'DEMO-SPU-001', product_name: '演示商品 01', current_stage: '稳定销售期', suggested_stage: '滞销观察期', confidence: 0.84, reason: '销量趋势下降且库存覆盖偏高', rule_version: 'demo-life-v3', review_period: '2026-W28', status: 'pending', evidence },
    { review_id: 'DEMO-LIFE-002', spu_code: 'DEMO-SPU-002', product_name: '演示商品 02', current_stage: '滞销观察期', suggested_stage: '清仓候选', confidence: 0.91, reason: '连续复盘未改善，库存覆盖超过阈值', rule_version: 'demo-life-v3', review_period: '2026-W28', status: 'pending', evidence: { ...evidence, stock_cover_days: 128 } }
  ]
});

export const mockLifecycleHistory = () => successResponse({
  status: 'mock', api_status: 'mock',
  summary: [
    { label: '本月复盘', value: 38 }, { label: '已确认', value: 12 }, { label: '已拒绝', value: 4 }, { label: '保持观察', value: 22 }
  ],
  items: [
    { history_id: 'DEMO-HIS-001', spu_code: 'DEMO-SPU-008', from_stage: '新品观察期', suggested_stage: '成长期', decision: 'confirmed', reviewer: '演示复盘员', reason: '销售与履约指标稳定', rule_version: 'demo-life-v3', reviewed_at: '2026-07-10 16:30', audit_evidence: { actor: 'demo-reviewer', before: '新品观察期', after: '成长期', action: 'mock_confirm' } },
    { history_id: 'DEMO-HIS-002', spu_code: 'DEMO-SPU-009', from_stage: '稳定销售期', suggested_stage: '滞销观察期', decision: 'rejected', reviewer: '演示复盘员', reason: '促销期间暂缓判断', rule_version: 'demo-life-v3', reviewed_at: '2026-07-09 11:20', audit_evidence: { actor: 'demo-reviewer', before: '稳定销售期', after: '稳定销售期', action: 'mock_reject' } }
  ]
});
