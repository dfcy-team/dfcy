import { describe, expect, it, vi } from 'vitest';
import { fetchAdvertisingOverview, fetchAdvertisingPerformance } from '../src/api/advertising';

const requestApi = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi, requestPendingOrMock: vi.fn() }));

describe('Shopee advertising API paths', () => {
  it.each([
    [fetchAdvertisingOverview, 'shop_daily'],
    [fetchAdvertisingPerformance, 'campaign_daily']
  ])('uses the backend /api prefix and preserves filters', (fetchReport, kind) => {
    const params = { store_id: 41, period_start: '2026-09-15', period_end: '2026-09-30' };
    fetchReport(params);
    expect(requestApi).toHaveBeenLastCalledWith({
      url: '/api/internal/analytics/advertising/', method: 'get', params: { kind, ...params }
    });
  });
});
