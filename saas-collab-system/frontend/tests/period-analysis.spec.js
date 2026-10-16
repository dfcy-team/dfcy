import { afterEach, describe, expect, it, vi } from 'vitest';
import { requestApi } from '../src/api/request';
import { analysisPayload, chartSegments, drillReportConfig, periodChange, pollAnalysisJob, rawDetailRoute } from '../src/views/reports/periodAnalysis';

vi.mock('../src/api/request', () => ({ requestApi: vi.fn() }));

afterEach(() => { vi.useRealTimers(); requestApi.mockReset(); });

describe('period analysis', () => {
  it('builds an immutable request shape and omits empty filters', () => {
    expect(analysisPayload({ dataset: 'sales', mode: 'monthly', year: 2026, filters: { store_id: 9, region: '', currency: null } })).toEqual({
      dataset: 'sales', mode: 'monthly', year: 2026, filters: { store_id: 9 }
    });
    expect(analysisPayload({ dataset: 'finance', mode: 'period', filters: {}, dateFrom: '2026-01-01', dateTo: '2026-01-31' })).toEqual({
      dataset: 'finance', mode: 'period', filters: {}, date_from: '2026-01-01', date_to: '2026-01-31'
    });
  });

  it('keeps missing values as gaps instead of drawing them as zero', () => {
    const points = [
      { current: { metrics: { amount: '4' } } },
      { current: null },
      { current: { metrics: { amount: '8' } } }
    ];
    const segments = chartSegments(points, 'amount', 'current', 100, 20);
    expect(segments).toHaveLength(2);
    expect(segments.flat().map(point => point.value)).toEqual([4, 8]);
  });

  it('uses server deltas and leaves comparisons with missing values empty', () => {
    expect(periodChange({ current: { metrics: { gross_sales: '20' } }, yoy: { metrics: { gross_sales: '10' } }, changes: { gross_sales: { yoy: { delta: '10', percent: '100' } } } }, 'gross_sales', 'yoy')).toEqual({ delta: '10', percent: '100' });
    expect(periodChange({ current: { metrics: { gross_sales: '20' } }, yoy: null }, 'gross_sales', 'yoy')).toBeNull();
  });

  it('builds raw detail routes with the applied period and dataset-specific filters', () => {
    const filters = { date_from: '2026-03-01', date_to: '2026-03-31', store_id: 7, currency: 'USD', region: 'US' };
    expect(rawDetailRoute('sales', filters, 'gross_sales')).toEqual({ path: '/sales-management/orders', query: { ...filters, exclude_cancelled: 'true', platform: undefined } });
    expect(rawDetailRoute('sales', filters, 'cancelled_order_count').query.order_status).toBe('cancelled');
    expect(rawDetailRoute('finance', filters, 'signed_amount')).toMatchObject({ path: '/finance/statements', query: { tab: 'transactions', period_start: '2026-03-01', period_end: '2026-03-31', store_id: 7, currency: 'USD' } });
    expect(rawDetailRoute('advertising', filters, 'expense')).toMatchObject({ path: '/analytics/advertising-overview', query: { view: 'details', kind: 'shop_daily', date_from: '2026-03-01', date_to: '2026-03-31', store_id: 7, currency: 'USD', region: 'US' } });
  });

  it('uses the supported country dimension for advertising aggregates and exposes computed ratios', () => {
    const config = drillReportConfig('advertising', { date_from: '2026-01-01', date_to: '2026-01-31' });
    expect(config.dimensions).toContain('country');
    expect(config.dimensions).not.toContain('region');
    expect(config.metrics).not.toContain('ctr');
    expect(config.metrics).toContain('clicks');
  });

  it('polls queued jobs until completion and returns the completed result', async () => {
    vi.useFakeTimers();
    requestApi.mockResolvedValueOnce({ success: true, data: { id: 'job-1', status: 'running' } })
      .mockResolvedValueOnce({ success: true, data: { id: 'job-1', status: 'completed', result: { series: [] } } });
    const pending = pollAnalysisJob('job-1', { intervalMs: 25, maxMs: 100 });
    await vi.advanceTimersByTimeAsync(25);
    await expect(pending).resolves.toMatchObject({ success: true, data: { status: 'completed', result: { series: [] } } });
    expect(requestApi).toHaveBeenCalledTimes(2);
  });

  it('treats expired jobs as terminal and stops polling', async () => {
    requestApi.mockResolvedValueOnce({ success: true, data: { id: 'job-old', status: 'expired' } });
    await expect(pollAnalysisJob('job-old', { maxMs: 50 })).resolves.toMatchObject({ data: { status: 'expired' } });
    expect(requestApi).toHaveBeenCalledTimes(1);
  });
});
