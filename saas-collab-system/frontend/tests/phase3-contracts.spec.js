import { describe, expect, it } from 'vitest';
import router from '../src/router';
import { normalizeApiResponse } from '../src/api/request';
import { mockBusinessOverview, mockInventoryAnalysis, mockSalesAnalysis } from '../src/mock/analytics';
import { mockInventoryAlerts, mockReplenishmentRecommendations } from '../src/mock/replenishment';
import { mockLifecycleDecisions, mockLifecycleReviews } from '../src/mock/lifecycle';
import { mockBusinessAlerts } from '../src/mock/alerts';
import { mockConfigChangeLogs, mockConfigDefinitions, mockConfigValues } from '../src/mock/configCenter';
import { mockFinanceAnalyticsOverview } from '../src/mock/financeAnalytics';
import { mockReportExports } from '../src/mock/reportExports';

const phase3Mocks = [
  mockBusinessOverview, mockSalesAnalysis, mockInventoryAnalysis, mockInventoryAlerts,
  mockReplenishmentRecommendations, mockLifecycleReviews, mockLifecycleDecisions, mockBusinessAlerts,
  mockConfigDefinitions, mockConfigValues, mockConfigChangeLogs, mockFinanceAnalyticsOverview, mockReportExports
];

const phase3Routes = [
  '/', '/analytics/sales', '/analytics/inventory', '/inventory/alerts', '/inventory/replenishment',
  '/lifecycle/reviews', '/lifecycle/history', '/alerts/business', '/settings/config-center',
  '/settings/config-versions', '/finance/analytics', '/reports/exports'
];

describe('Phase 3 frontend contracts', () => {
  it('keeps the unified response envelope', () => {
    expect(normalizeApiResponse({ answer: 42 })).toEqual({
      success: false,
      code: 'INVALID_API_RESPONSE',
      message: 'API response does not match the required envelope.',
      data: null,
      protocol_error: true
    });
  });

  it.each(phase3Mocks)('returns safe mock fallback data', (mockFactory) => {
    const response = mockFactory();
    expect(response.success).toBe(true);
    expect(response.code).toBe('OK');
    expect(response.data.api_status).toBe('mock');
  });

  it.each(phase3Routes)('registers route %s', (path) => {
    expect(router.resolve(path).matched.length).toBeGreaterThan(0);
  });
});
