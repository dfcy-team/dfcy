import { describe, expect, it } from 'vitest';
import { gmvCoverageLabel } from '../src/utils/gmvCoverageLabel';

const item = { store_code: 'S', currency: 'USD', timezone: 'UTC', platform_store_id: 'p',
  advertiser_count: 2, expected_days: 14, stored_days: 7 };
function report(count = 7) {
  return { date_from: '2026-10-28', date_to: '2026-11-03',
    selected_subjects: ['a', 'b'].map(advertiser_id => ({ store_code: 'S', advertiser_id, historical_binding_confirmed: true })),
    gmv_max_snapshots: Array.from({ length: count }, (_, i) => ({ ...item, advertiser_id: 'a',
      date: new Date(Date.parse('2026-10-28') + i * 86400000).toISOString().slice(0, 10) })) };
}
describe('GMV coverage wording', () => {
  it('uses the report account instead of the historical mapping denominator', () => {
    const result = gmvCoverageLabel(item, report());
    expect(result.label).toBe('所选范围已覆盖 · 7/7 广告户日');
    expect(result.type).toBe('success');
    expect(result.accountCount).toBe(1);
  });
  it('highlights a real single-day gap without the unrelated account denominator', () => {
    const result = gmvCoverageLabel(item, report(6));
    expect(result.label).toBe('缺 1 个广告户日 · 6/7 广告户日');
    expect(result.type).toBe('warning');
  });
  it('does not classify missing accounts as no_data or include another identity', () => {
    const data = report();
    data.gmv_max_snapshots.push({ ...data.gmv_max_snapshots[0], advertiser_id: 'b', platform_store_id: 'other' });
    expect(gmvCoverageLabel(item, data).accountCount).toBe(1);
    const empty = gmvCoverageLabel(item, { ...data, gmv_max_snapshots: [] });
    expect(empty.type).toBe('info');
    expect(empty.label).not.toContain('无广告数据');
  });
  it('keeps explicit empty, conflict and advertiser-only views distinct', () => {
    const data = report();
    data.gmv_max_snapshots.forEach(r => { r.collection_status = 'no_data'; });
    expect(gmvCoverageLabel(item, data).label).toBe('所选范围已覆盖 · 7/7 广告户日');
    expect(gmvCoverageLabel(item, data).dataAccounts).toBe(0);
    expect(gmvCoverageLabel({ ...item, conflict: true }, data).type).toBe('danger');
    expect(gmvCoverageLabel({ ...item, advertiser_id: 'a' }, data).accountCount).toBe(1);
  });
  it('still counts both accounts when both actually have interval reports', () => {
    const data = report();
    data.gmv_max_snapshots.push(...data.gmv_max_snapshots.map(r => ({ ...r, advertiser_id: 'b' })));
    const complete = gmvCoverageLabel(item, data);
    expect(complete.accountCount).toBe(2);
    expect(complete.label).toBe('所选范围已覆盖 · 14/14 广告户日');
    data.gmv_max_snapshots.pop();
    const partial = gmvCoverageLabel(item, data);
    expect(partial.type).toBe('warning');
    expect(partial.label).toBe('缺 1 个广告户日 · 13/14 广告户日');
  });
});
