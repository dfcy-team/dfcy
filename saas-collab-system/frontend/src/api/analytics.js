import { requestWithMockFallback } from './request';
import { mockBusinessOverview } from '../mock/analytics';

// Phase 3 backend analytics endpoints are pending until Development A merges them.
export const fetchBusinessOverview = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/analytics/overview/', params },
    mockBusinessOverview,
    'analytics.overview'
  );
