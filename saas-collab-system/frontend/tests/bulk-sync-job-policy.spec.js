import { describe, expect, it } from 'vitest';
import { buildBulkSyncJobPayload, classifyBulkSyncJobs } from '../src/utils/bulkSyncJobPolicy';

describe('批量同步策略', () => {
  it('only includes compatible idle jobs in the preview', () => {
    const jobs = [
      { id: 2, platform: 'shopee', resource_type: 'sales_order', status: 'failed' },
      { id: 8, platform: 'shopee', resource_type: 'sales_order', status: 'running' },
      { id: 14, platform: 'shopee', resource_type: 'sales_order', schedule_state: 'queued' },
      { id: 25, platform: 'lazada', resource_type: 'sales_order', status: 'idle' },
    ];
    const result = classifyBulkSyncJobs(jobs);
    expect(result.eligible.map(row => row.id)).toEqual([2]);
    expect(result.skipped.map(row => row.id)).toEqual([8, 14, 25]);
  });

  it('sends only selected limits and leaves schedule and query untouched', () => {
    expect(buildBulkSyncJobPayload(['max_pages', 'max_records'], {
      max_pages: 20, max_records: 2000, schedule_type: 'daily', query_mode: 'range',
    })).toEqual({ max_pages: 20, max_records: 2000 });
  });

  it('includes a complete weekly plan and explicit range when selected', () => {
    const result = buildBulkSyncJobPayload(['schedule', 'query'], {
      schedule_type: 'weekly', timezone: 'Asia/Shanghai', catch_up: 'skip',
      local_time: '02:00', weekdays: [1, 3], query_mode: 'range',
      range_start_at: '2026-08-01T00:00:00', range_end_at: '2026-08-31T23:59:59',
    });
    expect(result).toEqual({
      schedule_type: 'weekly', timezone: 'Asia/Shanghai', catch_up: 'skip',
      local_time: '02:00', weekdays: [1, 3], query_mode: 'range',
      range_start_at: '2026-08-01T00:00:00+08:00', range_end_at: '2026-08-31T23:59:59+08:00',
    });
  });
  it('preserves Beijing date ranges and explicitly zoned timestamps', () => {
    for (const range of [
      { range_start_at: '2026-08-01', range_end_at: '2026-08-31' },
      { range_start_at: '2026-08-01T00:00:00Z', range_end_at: '2026-08-31T23:59:59+08:00' },
    ]) {
      expect(buildBulkSyncJobPayload(['query'], { query_mode: 'range', ...range })).toEqual({ query_mode: 'range', ...range });
    }
  });
});
