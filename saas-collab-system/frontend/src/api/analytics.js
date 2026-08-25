import { requestApi, requestWithMockFallback } from './request';
import { mockBusinessOverview, mockInventoryAnalysis, mockSalesAnalysis } from '../mock/analytics';
import { buildAnalyticsQuery, normalizeAnalyticsResponse } from './uiP6Adapters';

const analyticsRequest = async (config, mockHandler, moduleName) =>
  normalizeAnalyticsResponse(
    await requestWithMockFallback(
      { ...config, params: buildAnalyticsQuery(config.params) },
      mockHandler,
      moduleName
    )
  );

export const fetchBusinessOverview = (params = {}) =>
  analyticsRequest(
    { method: 'get', url: '/api/internal/analytics/overview/', params },
    mockBusinessOverview,
    'analytics.overview'
  );

export const fetchMetricDefinitions = (params = {}) => requestApi({ method: 'get', url: '/api/internal/analytics/metrics/', params });
export const fetchMetricDefinition = (id) => requestApi({ method: 'get', url: `/api/internal/analytics/metrics/${id}/` });
export const fetchMetricAggregates = (params = {}) => requestApi({ method: 'get', url: '/api/internal/analytics/aggregates/', params });
export const fetchMetricAggregate = (id) => requestApi({ method: 'get', url: `/api/internal/analytics/aggregates/${id}/` });
export const runAggregateMock = (payload) => requestApi({ method: 'post', url: '/api/internal/analytics/aggregate-mock/', data: payload });

export const fetchSalesAnalysis = (params = {}) =>
  analyticsRequest(
    { method: 'get', url: '/api/internal/analytics/sales/', params },
    mockSalesAnalysis,
    'analytics.sales'
  );

export const fetchInventoryAnalysis = (params = {}) =>
  analyticsRequest(
    { method: 'get', url: '/api/internal/analytics/inventory/', params },
    mockInventoryAnalysis,
    'analytics.inventory'
  );

export const fetchAnalyticsFilters = (params = {}) =>
  analyticsRequest(
    { method: 'get', url: '/api/internal/analytics/filters/', params },
    () => ({ success: true, code: 'OK', message: '', data: { platforms: [], stores: [], sites: [], warehouses: [], currencies: [] } }),
    'analytics.filters'
  );
