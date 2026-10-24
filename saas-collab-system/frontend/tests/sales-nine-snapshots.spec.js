import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import SalesNineSnapshots from '../src/views/sales-management/SalesNineSnapshots.vue';
import SalesOperations from '../src/views/sales-management/SalesOperations.vue';
import { useAuthStore } from '../src/stores/auth';
import { fetchSalesNineSnapshots } from '../src/api/salesNineSnapshots';
import { fetchSalesOperations } from '../src/api/salesOperations';
import { fetchBoardFilters } from '../src/api/realtimeBoard';

vi.mock('../src/api/salesNineSnapshots', () => ({ fetchSalesNineSnapshots: vi.fn() }));
vi.mock('../src/api/salesOperations', () => ({ fetchSalesOperations: vi.fn() }));
vi.mock('../src/api/realtimeBoard', () => ({ fetchBoardFilters: vi.fn() }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ query: {} }) }));

const sample = { store_id: 14, store_name: '菲律宾店', country: 'PH', timezone: 'Asia/Manila', business_date: '2026-10-24', target_at: '2026-10-24T01:00:00Z', captured_at: '2026-10-24T01:03:00Z', status: 'unverified', integrity_reason: '源完整性未核验', groups: [{ currency: 'PHP', sales_amount: '125.4', order_count: 3, baselines: { previous_day: { sales_amount: null, sample_count: 0, status: 'missing_or_incompatible' }, previous_week_same_day: { sales_amount: '100.25', sample_count: 1, status: 'unverified' }, previous_week_average: { sales_amount: null, sample_count: 6, status: 'missing_or_incompatible' } } }] };
const snapshotResponse = (rows = [sample], has_next = false) => ({ success: true, data: { rows, has_next } });
const operationsResponse = { success: true, data: { rows: [], currency_groups: [], has_next: false } };
let wrapper;
beforeEach(() => {
  setActivePinia(createPinia()); useAuthStore().currentUser = { user_type: 'internal', permissions: ['sales_management.view'] };
  fetchSalesNineSnapshots.mockReset().mockResolvedValue(snapshotResponse());
  fetchSalesOperations.mockReset().mockResolvedValue(operationsResponse);
  fetchBoardFilters.mockReset().mockResolvedValue({ success: true, data: { platforms: [{ value: 'shopee', label: 'Shopee' }], stores: [{ id: 14, name: '菲律宾店', platform: 'shopee', country_code: 'PH' }] } });
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); };
});
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.clearAllMocks(); });

describe('销售09:00快照', () => {
  it('does not query until opened, then carries the applied platform, store, and region', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    expect(fetchSalesNineSnapshots).not.toHaveBeenCalled();
    await wrapper.findAll('.filters select')[0].setValue('shopee');
    await wrapper.findAll('.filters select')[1].setValue('PH');
    await wrapper.findAll('.filters select')[2].setValue('14');
    await wrapper.find('.filters').trigger('submit'); await flushPromises();
    expect(fetchSalesNineSnapshots).not.toHaveBeenCalled();
    await wrapper.find('.snapshot-state').trigger('click'); await flushPromises();
    expect(fetchSalesNineSnapshots).not.toHaveBeenCalled();
    await wrapper.find('.snapshot-query').trigger('submit'); await flushPromises();
    expect(fetchSalesNineSnapshots).toHaveBeenCalledTimes(1);
    expect(fetchSalesNineSnapshots.mock.calls[0][0]).toMatchObject({ platform: 'shopee', store_id: 14, region: 'PH', page: 1, page_size: 20 });
  });

  it('keeps missing values unknown and displays currency and order units', async () => {
    wrapper = mount(SalesNineSnapshots, { props: { scope: {} } });
    expect(fetchSalesNineSnapshots).not.toHaveBeenCalled();
    await wrapper.find('.snapshot-query').trigger('submit'); await flushPromises();
    expect(wrapper.text()).toContain('125.40 PHP'); expect(wrapper.text()).toContain('3 单');
    expect(wrapper.text()).toContain('缺样 · — PHP'); expect(wrapper.text()).toContain('100.25 PHP（未核验）');
    expect(wrapper.text()).toContain('Asia/Manila'); expect(wrapper.text()).toContain('目标时间'); expect(wrapper.text()).toContain('采集时间');
    expect(wrapper.text()).not.toContain('0.00 PHP'); expect(wrapper.text()).not.toContain('%');
  });

  it('aborts superseded requests and ignores stale responses', async () => {
    let resolveFirst;
    fetchSalesNineSnapshots.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; })).mockResolvedValueOnce(snapshotResponse([{ ...sample, store_name: '新快照' }]));
    wrapper = mount(SalesNineSnapshots, { props: { scope: {} } });
    await wrapper.find('.snapshot-query').trigger('submit'); await flushPromises();
    const oldSignal = fetchSalesNineSnapshots.mock.calls[0][1];
    await wrapper.find('input[type="date"]').setValue('2026-10-23'); await wrapper.find('.snapshot-query').trigger('submit'); await flushPromises();
    expect(oldSignal.aborted).toBe(true); expect(wrapper.text()).toContain('新快照');
    resolveFirst(snapshotResponse([{ ...sample, store_name: '过期响应' }])); await flushPromises();
    expect(wrapper.text()).not.toContain('过期响应'); expect(wrapper.text()).toContain('新快照');
    const currentSignal = fetchSalesNineSnapshots.mock.calls.at(-1)[1]; wrapper.unmount(); wrapper = null;
    expect(currentSignal.aborted).toBe(true);
  });

  it('keeps pagination on the explicitly queried date while a new date remains a draft', async () => {
    fetchSalesNineSnapshots.mockResolvedValueOnce(snapshotResponse([sample], true)).mockResolvedValueOnce(snapshotResponse([sample], false));
    wrapper = mount(SalesNineSnapshots, { props: { scope: { platform: 'shopee' } } });
    await wrapper.find('input[type="date"]').setValue('2026-10-20');
    await wrapper.find('.snapshot-query').trigger('submit'); await flushPromises();
    expect(fetchSalesNineSnapshots.mock.calls[0][0].date).toBe('2026-10-20');
    await wrapper.find('input[type="date"]').setValue('2026-10-21');
    await wrapper.find('.pagination button:last-child').trigger('click'); await flushPromises();
    expect(fetchSalesNineSnapshots.mock.calls[1][0]).toMatchObject({ date: '2026-10-20', page: 2, platform: 'shopee' });
  });
});
