import { requestWithMockFallback } from './request';
import { mockBusinessOverview, mockInventoryAnalysis, mockSalesAnalysis } from '../mock/analytics';

// Phase 3 backend analytics endpoints are pending until Development A merges them.
export const fetchBusinessOverview = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/analytics/overview/', params },
    mockBusinessOverview,
    'analytics.overview'
  );

export const fetchSalesAnalysis = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/analytics/sales/', params },
    mockSalesAnalysis,
    'analytics.sales'
  );

export const fetchInventoryAnalysis = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/internal/analytics/inventory/', params },
    mockInventoryAnalysis,
    'analytics.inventory'
  );
