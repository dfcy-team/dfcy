import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Overview from '../src/components/TikTokAdsDailySpendOverview.vue';
import { fetchTikTokDailySpend } from '../src/api/advertising';

vi.mock('../src/api/advertising', () => ({ fetchTikTokDailySpend: vi.fn() }));
const wrappers = [];
const subject = { mapping_id: 1, store_id: 7, store_code: 'TK1', store_name: '店铺一', advertiser_id: '100',
  collection_enabled: false, local_evidence: 'unverified' };
const response = (spend = '0.000000') => ({ success: true, data: {
  subjects: [subject], selected_subjects: [subject], warnings: ['collection_disabled', 'local_evidence_unverified'],
  coverage: { visible_mappings: 1, mapping_days: 2, stored: 1, missing: 1, explicit_zero: 1 },
  complete: false, totals: [{ currency: 'PHP', total: null, known_subtotal: spend, expected_days: 2, stored_days: 1, missing_days: 1 }],
  results: [{ id: 1, date: '2026-10-01', spend, currency: 'PHP', mapping_timezone: 'Asia/Manila' }],
  page: 1, page_size: 50, count: 1,
} });
function render(active = true) {
  const wrapper = mount(Overview, { props: { active }, global: { plugins: [ElementPlus] } });
  wrappers.push(wrapper);
  return wrapper;
}
const query = (wrapper) => wrapper.findAllComponents({ name: 'ElButton' }).find((item) => item.text() === '查询已存数据').trigger('click');
async function dates(wrapper, from, to) {
  const fields = wrapper.findAllComponents({ name: 'ElDatePicker' });
  fields[0].vm.$emit('update:modelValue', from);
  fields[1].vm.$emit('update:modelValue', to);
  await wrapper.vm.$nextTick();
}
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

beforeEach(() => {
  fetchTikTokDailySpend.mockReset();
  fetchTikTokDailySpend.mockResolvedValue(response());
});
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.useRealTimers();
});

describe('TikTok stored spend', () => {
  it('shows GMV snapshots separately without changing BASIC totals', async () => {
    const payload = response('3.000000');
    payload.data.gmv_max_snapshots = [{ date: '2026-10-30', store_code: 'TK1', advertiser_name: 'Example Ads',
      advertiser_id: '100', currency: 'USD', cost: '71.02', gross_revenue: '489.61', orders: 54,
      campaign_count: 18, timezone: 'Asia/Manila' }];
    fetchTikTokDailySpend.mockResolvedValue(payload);
    const wrapper = render();
    await flushPromises();
    expect(wrapper.text()).toContain('Example Ads');
    expect(wrapper.text()).toContain('71.02');
    const tables = wrapper.findAllComponents({ name: 'ElTable' });
    expect(tables[0].props('data')).toEqual(payload.data.gmv_max_snapshots);
    expect(tables[2].props('data')[0].known_subtotal).toBe('3.000000');
    expect(fetchTikTokDailySpend).toHaveBeenCalledTimes(1);
  });
  it('loads only on selection with the last seven completed Manila days', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-17T16:30:00Z'));
    const wrapper = render(false);
    expect(fetchTikTokDailySpend).not.toHaveBeenCalled();
    await wrapper.setProps({ active: true });
    await flushPromises();
    expect(fetchTikTokDailySpend).toHaveBeenLastCalledWith({
      date_from: '2026-10-11', date_to: '2026-10-17', page: 1, page_size: 50,
    });
    await wrapper.setProps({ active: false });
    expect(wrapper.text()).not.toContain('0.000000');
  });

  it('rejects overlong dates and clears old results immediately on date changes', async () => {
    const wrapper = render();
    await flushPromises();
    expect(wrapper.text()).toContain('0.000000');
    await dates(wrapper, '2026-10-01', '2026-11-01');
    expect(wrapper.text()).not.toContain('0.000000');
    await query(wrapper);
    expect(fetchTikTokDailySpend).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain('31');
  });

  it('shows unknown versus zero, status warnings and scoped subject dropdowns', async () => {
    const wrapper = render();
    await flushPromises();
    expect(wrapper.text()).toContain('未知');
    expect(wrapper.text()).toContain('0.000000');
    expect(wrapper.text()).toContain('当前元数据');
    expect(wrapper.text()).toContain('历史数据仍可查看');
    expect(wrapper.text()).toContain('未核验');
    const selects = wrapper.findAllComponents({ name: 'ElSelect' });
    expect(selects).toHaveLength(2);
    const options = wrapper.findAllComponents({ name: 'ElOption' });
    expect(options.map((item) => item.props('value'))).toEqual([7, '100']);
    selects[0].vm.$emit('update:modelValue', 7);
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).not.toContain('0.000000');
    await query(wrapper);
    expect(fetchTikTokDailySpend).toHaveBeenLastCalledWith(expect.objectContaining({ store_id: 7 }));
  });

  it('shows failure without stale content or fabricated data', async () => {
    const wrapper = render();
    await flushPromises();
    fetchTikTokDailySpend.mockRejectedValueOnce(new Error('forbidden'));
    await query(wrapper);
    await flushPromises();
    expect(wrapper.text()).toContain('forbidden');
    expect(wrapper.text()).not.toContain('0.000000');
    expect(wrapper.findAllComponents({ name: 'ElOption' })).toHaveLength(0);
  });

  it('ignores an older delayed success after a newer query succeeds', async () => {
    const first = deferred(), second = deferred();
    fetchTikTokDailySpend.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = render();
    await dates(wrapper, '2026-10-01', '2026-10-02');
    await query(wrapper);
    second.resolve(response('2.000002'));
    await flushPromises();
    expect(wrapper.text()).toContain('2.000002');
    first.resolve(response('1.000001'));
    await flushPromises();
    expect(wrapper.text()).toContain('2.000002');
    expect(wrapper.text()).not.toContain('1.000001');
  });

  it('ignores delayed old success after a newer query fails', async () => {
    const first = deferred();
    fetchTikTokDailySpend.mockReturnValueOnce(first.promise);
    const wrapper = render();
    fetchTikTokDailySpend.mockRejectedValueOnce(new Error('new failure'));
    await dates(wrapper, '2026-10-01', '2026-10-02');
    await query(wrapper);
    await flushPromises();
    first.resolve(response('1.000001'));
    await flushPromises();
    expect(wrapper.text()).toContain('new failure');
    expect(wrapper.text()).not.toContain('1.000001');
  });

  it('ignores in-flight responses after filters change or tab is deselected', async () => {
    const first = deferred(), second = deferred();
    fetchTikTokDailySpend.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = render();
    await dates(wrapper, '2026-10-01', '2026-10-02');
    first.resolve(response('1.000001'));
    await flushPromises();
    expect(wrapper.text()).not.toContain('1.000001');
    await query(wrapper);
    await wrapper.setProps({ active: false });
    second.resolve(response('2.000002'));
    await flushPromises();
    expect(wrapper.text()).not.toContain('2.000002');
  });
});
