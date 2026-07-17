import { requestApi, requestWithMockFallback } from './request';
import { mockFinanceAnalyticsOverview } from '../mock/financeAnalytics';
import { buildFinanceAnalyticsQuery } from './uiP6Adapters';

export const fetchFinanceAnalyticsOverview = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/analytics/overview/', params: buildFinanceAnalyticsQuery(params) },
    mockFinanceAnalyticsOverview,
    'finance.analytics.overview'
  );

export const fetchFinanceAnalyticsReconciliation = (params = {}) => requestApi({ method: 'get', url: '/api/finance/analytics/reconciliation/', params: buildFinanceAnalyticsQuery(params) });
export const fetchFinanceAnalyticsExceptions = (params = {}) => requestApi({ method: 'get', url: '/api/finance/analytics/exceptions/', params: buildFinanceAnalyticsQuery(params) });
