import { successResponse } from './index';

const recommendation = {
  id: 1,
  spu: 1,
  sku: 1,
  spu_code: 'MOCK-SPU-001',
  sku_code: 'MOCK-SKU-001',
  current_status: 'new',
  suggested_status: 'clearance',
  recommended_status: 'clearance',
  reason_code: 'LOW_SELL_THROUGH',
  reason_detail: 'Mock low sell-through recommendation for Phase 2 UI verification only.',
  confidence: 0.72,
  source_type: 'api',
  calculated_at: '2026-07-10T00:00:00Z',
  recommendation_status: 'pending',
  status: 'pending',
  created_at: '2026-07-10T00:00:00Z',
  confirmed_by_id: '',
  confirmed_by: '',
  confirmed_at: '',
  source_snapshot: {
    id: 1,
    source: 'system_rule',
    metrics_payload: { sell_through_rate: 0.18 },
    calculated_status: 'clearance'
  }
};

const transition = {
  id: 1,
  spu: 1,
  sku: 1,
  spu_code: 'MOCK-SPU-001',
  sku_code: 'MOCK-SKU-001',
  from_status: 'new',
  to_status: 'active',
  trigger_type: 'manual',
  source_type: 'manual',
  reason_code: 'MANUAL_APPROVED',
  reason: 'Mock transition for Phase 2 page verification only.',
  approved_by_id: 1,
  changed_by: 'mock-reviewer',
  changed_at: '2026-07-10T00:00:00Z',
  created_at: '2026-07-10T00:00:00Z'
};

export const mockStatusDashboard = () => successResponse({
  status: 'mock',
  module: 'products.status.dashboard',
  items: [
    { status_name: 'new', count: 12 },
    { status_name: 'active', count: 48 },
    { status_name: 'slow_moving', count: 5 },
    { status_name: 'clearance', count: 2 },
    { status_name: 'stopped', count: 1 },
    { status_name: 'archived', count: 0 }
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
