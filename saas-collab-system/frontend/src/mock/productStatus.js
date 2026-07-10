import { successResponse } from './index';

const recommendation = {
  id: 1,
  spu_code: 'MOCK-SPU-001',
  sku_code: 'MOCK-SKU-001',
  current_status: '新品',
  suggested_status: '清仓',
  reason_code: 'LOW_SELL_THROUGH',
  reason_detail: 'Mock低动销建议，仅用于阶段2页面验证',
  confidence: 0.72,
  source_type: 'api',
  calculated_at: '2026-07-10T00:00:00Z',
  recommendation_status: 'pending',
  confirmed_by: '',
  confirmed_at: ''
};

const transition = {
  id: 1,
  spu_code: 'MOCK-SPU-001',
  sku_code: 'MOCK-SKU-001',
  from_status: '新品',
  to_status: '正常销售',
  source_type: 'manual',
  reason_code: 'MANUAL_APPROVED',
  changed_by: 'mock-reviewer',
  changed_at: '2026-07-10T00:00:00Z'
};

export const mockStatusDashboard = () => successResponse({
  status: 'mock',
  module: 'products.status.dashboard',
  items: [
    { status_name: '新品', count: 12 },
    { status_name: '正常销售', count: 48 },
    { status_name: '滞销', count: 5 },
    { status_name: '清仓', count: 2 },
    { status_name: '停售', count: 1 },
    { status_name: '归档', count: 0 }
  ]
});

export const mockStatusRecommendations = () => successResponse({
  status: 'mock',
  module: 'products.status.recommendations',
  items: [recommendation]
});

export const mockStatusRecommendationDetail = () => successResponse({
  status: 'mock',
  module: 'products.status.recommendations.detail',
  ...recommendation,
  evidence: {
    api_signal: 'mock api source',
    rpa_readback: 'mock rpa readback source',
    manual_note: 'placeholder only'
  }
});

export const mockStatusTransitions = () => successResponse({
  status: 'mock',
  module: 'products.status.transitions',
  items: [transition]
});
