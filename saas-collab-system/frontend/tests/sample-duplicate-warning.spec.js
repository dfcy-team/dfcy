import { flushPromises } from '@vue/test-utils';
import { effectScope, ref } from 'vue';
import { expect, it, vi } from 'vitest';

const { fetchDuplicateSampleRecords } = vi.hoisted(() => ({ fetchDuplicateSampleRecords: vi.fn() }));
vi.mock('../src/api/influencers', () => ({ fetchDuplicateSampleRecords }));

import { useDuplicateSampleWarning } from '../src/views/influencers/useDuplicateSampleWarning';

it('uses only creator selection, ignores stale matches and displays the five configured states', async () => {
  const creator = ref(null);
  const scope = effectScope();
  const warning = scope.run(() => useDuplicateSampleWarning(() => creator.value));
  try {
    expect(fetchDuplicateSampleRecords).not.toHaveBeenCalled();
    let resolveOld;
    fetchDuplicateSampleRecords.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    creator.value = 628;
    await flushPromises();
    const statuses = ['pending', 'shipped', 'delivered', 'overdue', 'blacklisted', 'completed', 'cancelled', 'published'];
    fetchDuplicateSampleRecords.mockResolvedValueOnce({ success: true, data: {
      records: statuses.map(status => ({ fulfillment_no: status, status }))
    } });
    creator.value = 629;
    await flushPromises();
    expect(fetchDuplicateSampleRecords).toHaveBeenLastCalledWith(629);
    for (const label of ['待处理', '已发货', '已送达', '已逾期', '已拉黑']) expect(warning.value).toContain(label);
    for (const key of ['completed', 'cancelled', 'published']) expect(warning.value).not.toContain(key);
    resolveOld({ success: true, data: { records: [{ fulfillment_no: 'stale', status: 'pending' }] } });
    await flushPromises();
    expect(warning.value).not.toContain('stale');
    creator.value = null;
    await flushPromises();
    expect(warning.value).toBe('');
  } finally {
    scope.stop();
  }
});
