import { describe, expect, it } from 'vitest';
import { formatField, formatMetric, trendSeries, statusLabel } from '../src/views/sales-management/display';
import { salesPageContracts } from '../src/views/sales-management/pageContracts';

describe('销售字段展示', () => {
  it('distinguishes missing values, zero, percentages and identifiers', () => {
    expect(formatField(null, { format: 'money' })).toBe('—');
    expect(formatField('', { numeric: true })).toBe('—');
    expect(formatField('0.0000', { format: 'money' })).toBe('0.00');
    expect(formatField('12345.6789', { format: 'money' })).toBe('12,345.68');
    expect(formatField('-45.5', { format: 'money' })).toBe('-45.50');
    expect(formatField('0.0523', { format: 'ratio' })).toBe('5.23%');
    expect(formatField('00123456789012345678')).toBe('00123456789012345678');
    expect(formatField(false, { status: true })).toBe('否');
    expect(formatField({ PHP: 5 })).toBe('—');
  });
  it('normalizes dates to explicit UTC without guessing an absent timezone', () => {
    expect(formatField('2026-09-11T10:03:00+08:00', { format: 'datetime' })).toBe('2026-09-11 02:03:00');
    expect(formatField('bad-date', { format: 'datetime' })).toBe('—');
    expect(formatField('2026-09-11 10:03:00', { format: 'datetime' })).toBe('—');
  });
  it('labels known states and preserves unknown provider values', () => {
    expect(statusLabel('mapped')).toBe('已关联');
    expect(statusLabel('unmapped')).toBe('未关联');
    expect(statusLabel('cancelled')).toBe('已取消');
    expect(statusLabel('NEW_PROVIDER_STATUS')).toBe('NEW_PROVIDER_STATUS');
    expect(formatField('tiktok', { format: 'platform' })).toBe('TikTok Shop');
  });
  it('formats metrics without combining currencies or treating ratios as money', () => {
    expect(formatMetric({ code: 'gross_sales', label: 'Sales', value: '1234.5', unit: 'PHP' })).toMatchObject({ label: '销售额', display: '1,234.50', unit: 'PHP' });
    expect(formatMetric({ code: 'refund_rate', value: '0.125', unit: 'ratio' })).toMatchObject({ display: '12.50%', unit: '' });
  });
  it('splits the real currency-object trend and keeps negative and zero facts', () => {
    const series = trendSeries([
      { date: '2026-09-10', net_sales: { PHP: '100', THB: '0' } },
      { date: '2026-09-11', net_sales: { PHP: '-25' } }
    ]);
    expect(series).toEqual([
      { currency: 'PHP', points: [{ label: '2026-09-10', value: '100' }, { label: '2026-09-11', value: '-25' }] },
      { currency: 'THB', points: [{ label: '2026-09-10', value: '0' }] }
    ]);
  });
  it('shows store provenance for SKU rows and field units on all pages', () => {
    expect(salesPageContracts.skus.columns.map(c => c.prop)).toEqual(expect.arrayContaining(['store_name', 'platform', 'region']));
    for (const contract of Object.values(salesPageContracts)) {
      for (const column of contract.columns) {
        if (column.format === 'datetime') expect(column.label).toContain('UTC');
      }
    }
    expect(salesPageContracts.orders.description).not.toContain('不提供独立退款页面');
  });
});
