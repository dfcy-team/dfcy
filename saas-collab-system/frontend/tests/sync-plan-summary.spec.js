import { describe, expect, it } from 'vitest';
import { syncActualRange, syncBeijingTime, syncHistoricalPlanSummary, syncPlanSummary } from '../src/utils/syncPresentation';

describe('同步计划摘要', () => {
  it('呈现当前调度、采集范围、时区、补跑策略和下次执行时间', () => {
    expect(syncPlanSummary({ schedule_type: 'interval', interval_minutes: 30, query_mode: 'incremental', lookback_days: 3, timezone: 'Asia/Shanghai', catch_up: 'run_once' }))
      .toBe('每 30 分钟执行 · 按更新时间回看 3 天 · 北京时间 · 错过后补跑一次');
    expect(syncBeijingTime('2026-09-30T00:00:00Z')).toBe('2026-09-30 08:00:00');
  });

  it('历史摘要只使用快照，并明确标记未记录的采集规则', () => {
    expect(syncHistoricalPlanSummary({ schedule_type: 'interval', interval_minutes: 15, timezone: 'Asia/Shanghai', catch_up: 'skip' }))
      .toBe('每 15 分钟执行 · 北京时间 · 错过后跳过 · 未记录采集规则');
    expect(syncHistoricalPlanSummary({ schedule_type: 'interval', interval_minutes: 15 }))
      .toBe('每 15 分钟执行 · 时区未知 · 未记录错过策略 · 未记录采集规则');
    expect(syncHistoricalPlanSummary({ timezone: 'UTC' })).toBe('计划类型未知 · UTC · 未记录采集规则');
    expect(syncHistoricalPlanSummary(null)).toBe('未记录当次计划');
  });

  it('根据资源类型描述真实采集口径', () => {
    expect(syncPlanSummary({ resource_type: 'refund_return', query_mode: 'incremental', lookback_days: 2, catch_up: 'skip' })).toContain('按申请时间回看 2 天');
    expect(syncPlanSummary({ resource_type: 'settlement_bill', query_mode: 'incremental', lookback_days: 4 })).toContain('按平台记账时间回看 4 天');
    expect(syncPlanSummary({ resource_type: 'inventory_snapshot', query_mode: 'incremental', lookback_days: 1 })).toContain('读取当前库存快照');
    expect(syncPlanSummary({ resource_type: 'platform_product', product_full_sync: true, query_mode: 'incremental' })).toContain('全量商品，不按时间过滤');
    expect(syncPlanSummary({ resource_type: 'sales_order', query_mode: 'range', range_start_at: '2026-09-29T16:00:00Z', range_end_at: '2026-09-30' })).toContain('固定范围 2026-09-30 至 2026-09-30');
  });

  it('将日志记录的真实采集边界精确显示到秒', () => {
    expect(syncActualRange({ time_from: 1790726400, time_to: 1790726467 })).toBe('2026-09-30 08:00:00 至 2026-09-30 08:01:07');
    expect(syncActualRange({})).toBe('— 至 —');
  });
});
