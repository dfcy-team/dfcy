import { requestApi, requestWithMockFallback } from './request';
import { mockFinanceAnalyticsOverview } from '../mock/financeAnalytics';

export const fetchFinanceAnalyticsOverview = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/analytics/overview/', params },
    mockFinanceAnalyticsOverview,
    'finance.analytics.overview'
  );

export const fetchFinanceAnalyticsReconciliation = (params = {}) => requestApi({ method: 'get', url: '/api/finance/analytics/reconciliation/', params });
export const fetchFinanceAnalyticsExceptions = (params = {}) => requestApi({ method: 'get', url: '/api/finance/analytics/exceptions/', params });
