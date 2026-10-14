import { describe, expect, it } from 'vitest';
import { BD_COST_COLUMNS, costCsvColumns, costDisplay } from '../src/utils/bdPerformanceCosts';

describe('BD actual cost presentation', () => {
  const standard = BD_COST_COLUMNS[1];
  const format = (value) => `CNY ${value}`;

  it('lists all three components and total in the core report', () => {
    expect(BD_COST_COLUMNS.map((column) => column.label)).toEqual(['送样成本', '实际标准佣金', '实际广告佣金', '总成本']);
  });

  it('treats an explicitly complete zero as a real zero', () => {
    expect(costDisplay({ actual_standard_commission: '0.0000', actual_standard_commission_complete: true }, standard, format)).toBe('CNY 0.0000');
  });

  it('marks partial known amounts including zero instead of inventing a complete amount', () => {
    expect(costDisplay({ actual_standard_commission: null, known_actual_standard_commission: '0.0000', actual_standard_commission_complete: false }, standard, format)).toBe('已知 CNY 0.0000（未完整）');
    expect(costDisplay({ actual_standard_commission: '8.0000', known_actual_standard_commission: '3.0000', actual_standard_commission_complete: false }, standard, format)).toBe('已知 CNY 3.0000（未完整）');
    expect(costDisplay({}, standard, format)).toBe('待补齐');
  });

  it('exports full amounts, separately labelled known subtotals and completeness', () => {
    const columns = costCsvColumns();
    expect(columns).toHaveLength(18);
    expect(columns).toContainEqual(['实际广告佣金', 'actual_ads_commission']);
    expect(columns).toContainEqual(['总成本已知小计', 'known_total_cost']);
    expect(columns).toContainEqual(['总成本完整', 'cost_complete']);
    expect(columns).toContainEqual(['缺少实际广告佣金汇率记录', 'missing_actual_ads_commission_exchange_rate_count']);
  });
});
