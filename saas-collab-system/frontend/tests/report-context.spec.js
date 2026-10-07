import { describe, expect, it } from 'vitest';
import { accessFailure, defaultReportFilters, queryScope, reportQuality, reportResponseError } from '../src/views/reports/reportContext';

describe('报表口径与数据质量', () => {
  it('uses bounded defaults without inventing unsupported filters', () => {
    expect(defaultReportFilters({ id: 'finance', filters: ['date_from', 'date_to'] }, new Date('2026-10-03T08:00:00Z'))).toEqual({ date_from: '2026-10-01', date_to: '2026-10-03' });
    expect(defaultReportFilters({ id: 'inventory', filters: ['warehouse_id'] })).toEqual({});
  });
  it('preserves literal SKU codes and explicitly states virtual and currency scope', () => {
    expect(queryScope({ dataset: 'inventory_value', filters: { sku: ' 旧-A ', sku_mode: 'related' } }).join(' ')).toContain(' 旧-A ');
    expect(queryScope({ dataset: 'inventory_value' })).toEqual(expect.arrayContaining(['排除虚拟商品', '金额按成本币种分组']));
  });
  it('does not turn unavailable, empty-denominator or truncated quality into complete totals', () => {
    const config = { metrics: ['sku_count', 'valued_count', 'missing_cost_count'] };
    const cards = reportQuality({ config, rows: [{ sku_count: 0, valued_count: 0, missing_cost_count: 0 }] }, 'inventory_value');
    expect(cards[0].value).toBe('—'); expect(cards[2].value).toBe('未提供');
    expect(reportQuality({ config, rows: [], truncated: true }, 'inventory_value')).toEqual([]);
  });
  it('counts records rather than summing cross-currency amounts', () => {
    const config = { metrics: ['transaction_count', 'unknown_count', 'unmatched_count'] };
    const cards = reportQuality({ config, rows: [{ transaction_count: 7, unknown_count: 4, unmatched_count: 1 }, { transaction_count: 3, unknown_count: 2, unmatched_count: 1 }] }, 'finance');
    expect(cards[0].value).toBe('10'); expect(cards[1].note).toContain('60.0%'); expect(cards[2].label).toContain('冲突');
  });
  it('keeps the HTTP authorization status even when the response message is generic', () => {
    expect(accessFailure(reportResponseError({ http_status: 403, message: '请求错误' }))).toBe(true);
    expect(accessFailure(reportResponseError({ http_status: 504, message: '请求错误' }))).toBe(false);
  });
});
