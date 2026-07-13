import { requestWithMockFallback } from './request';
import { mockFinanceAnalyticsOverview } from '../mock/financeAnalytics';

export const fetchFinanceAnalyticsOverview = (params = {}) =>
  requestWithMockFallback(
    { method: 'get', url: '/api/finance/analytics/overview/', params },
    mockFinanceAnalyticsOverview,
    'finance.analytics.overview'
  );
