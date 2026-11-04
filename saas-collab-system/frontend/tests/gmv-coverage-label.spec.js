import { describe, expect, it } from 'vitest';
import { gmvCoverageLabel } from '../src/utils/gmvCoverageLabel';

const item = { api_coverage: { account_count: 1, expected_days: 7, stored_days: 7,
  complete: true, unverified_report_days: 0 } };
describe('GMV coverage wording', () => {
  it('uses the report account instead of the historical mapping denominator', () => {
    const result = gmvCoverageLabel(item);
    expect(result.label).toBe('所选范围已覆盖 · 7/7 广告户日');
    expect(result.type).toBe('success');
    expect(result.accountCount).toBe(1);
  });
  it('highlights a real single-day gap without the unrelated account denominator', () => {
    const result = gmvCoverageLabel({ api_coverage: { ...item.api_coverage, stored_days: 6, complete: false } });
    expect(result.label).toBe('缺 1 个广告户日 · 6/7 广告户日');
    expect(result.type).toBe('warning');
  });
  it('does not classify missing accounts as no_data or include another identity', () => {
    const empty = gmvCoverageLabel({ stored_days: 7, expected_days: 7 }, { gmv_max_snapshots: [item] });
    expect(empty.type).toBe('info');
    expect(empty.label).not.toContain('无广告数据');
  });
  it('keeps explicit empty, conflict and advertiser-only views distinct', () => {
    expect(gmvCoverageLabel(item).label).toBe('所选范围已覆盖 · 7/7 广告户日');
    expect(gmvCoverageLabel({ ...item, conflict: true }).type).toBe('danger');
    expect(gmvCoverageLabel({ ...item, advertiser_id: 'a' }).accountCount).toBe(1);
  });
  it('still counts both accounts when both actually have interval reports', () => {
    const data = { api_coverage: { ...item.api_coverage, account_count: 2, stored_days: 14, expected_days: 14 } };
    const complete = gmvCoverageLabel(data);
    expect(complete.accountCount).toBe(2);
    expect(complete.label).toBe('所选范围已覆盖 · 14/14 广告户日');
    data.api_coverage.stored_days = 13;
    data.api_coverage.complete = false;
    const partial = gmvCoverageLabel(data);
    expect(partial.type).toBe('warning');
    expect(partial.label).toBe('缺 1 个广告户日 · 13/14 广告户日');
  });
});
