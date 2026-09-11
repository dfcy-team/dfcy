import { describe, it, expect } from 'vitest';
import { buildAnalyticsQuery as buildInventoryQuery, normalizeInventoryAnalysisResponse } from '../src/api/uiP6Adapters';

const response = (trend = []) => ({ success: true, data: {
  count: 1, quality: { score: 0, status: 'warning', metric_version: 'inventory_snapshot.v1', mapped_count: 0, total_count: 1 },
  results: [{ source_sku: 'FAKE-SKU', internal_sku: null, warehouse_name: '测试仓', on_hand_qty: 8, snapshot_at_utc: '2026-08-17T08:00:00Z' }],
  trend,
} });

describe('真实库存分析适配', () => {
  it('preserves the supported risk and warehouse filters', () => {
    expect(buildInventoryQuery({ warehouse: 11, risk: 'low', date_range: ['2026-08-17', '2026-08-18'] }))
      .toEqual({ warehouse_id: 11, risk: 'low', period_start: '2026-08-17', period_end: '2026-08-18' });
  });
  it('shows source SKU and unmapped state without calling inventory unreliable', () => {
    const data = normalizeInventoryAnalysisResponse(response()).data;
    expect(data.results[0]).toMatchObject({ source_sku: 'FAKE-SKU', internal_sku: '未关联', on_hand_qty: 8 });
    expect(data.quality.status_label).toBe('待关联');
    expect(data.quality.note).toContain('不代表库存数量错误');
  });
  it('does not present one snapshot day as a coverage trend', () => {
    const data = normalizeInventoryAnalysisResponse(response([{ date: '2026-08-17', total: 8 }])).data;
    expect(data.trend).toEqual([]);
    expect(data.trend_message).toContain('仅有 1 天');
  });
  it('maps daily quantities to chart labels and values including zero', () => {
    const data = normalizeInventoryAnalysisResponse(response([{ date: '2026-08-17', total: 8 }, { date: '2026-08-18', total: 0 }])).data;
    expect(data.trend).toEqual([{ label: '2026-08-17', value: 8 }, { label: '2026-08-18', value: 0 }]);
  });
  it('never treats legacy metric aggregates as warehouse facts', () => {
    const data = normalizeInventoryAnalysisResponse({ success: true, data: { results: [{ metric_code: 'demo', value: 999 }], quality: {} } }).data;
    expect(data.results).toEqual([]);
    expect(data.metrics).toEqual([]);
    expect(data.quality.score).toBeNull();
  });
});
