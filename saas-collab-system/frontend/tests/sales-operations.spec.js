import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { reactive } from 'vue';
import SalesOperations from '../src/views/sales-management/SalesOperations.vue';
import { useAuthStore } from '../src/stores/auth';
import { fetchSalesOperations } from '../src/api/salesOperations';
import { dateRange, amount, percent, validRange } from '../src/views/sales-management/salesOperations';
vi.mock('../src/api/salesOperations', () => ({ fetchSalesOperations: vi.fn() }));
vi.mock('../src/api/realtimeBoard', () => ({ fetchBoardFilters: vi.fn(async () => ({ success: true, data: { stores: [] } })) }));
const push = vi.fn();
const routeQuery = reactive({});
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => ({ query: routeQuery }) }));
const row = { store_id: 2, store_name: '菲律宾店铺', country: 'PH', currency: 'PHP', sales_amount: '70', previous_sales_amount: '100', change_percent: '-30', ad_spend: null, roi: null, order_count: 2 };
const response = (rows = [row]) => ({ success: true, data: { rows, currency_groups: [{ ...row }], has_next: false } });
let wrapper;
beforeEach(() => { Object.keys(routeQuery).forEach(key => delete routeQuery[key]); push.mockReset(); setActivePinia(createPinia()); useAuthStore().currentUser = { user_type: 'internal', permissions: ['sales_management.view','sales_management.skus.view'] }; fetchSalesOperations.mockReset().mockResolvedValue(response()); HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); }; HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); }; });
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.clearAllMocks(); });
describe('销售日常经营', () => {
  it('defaults to yesterday with one summary request and no polling', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    expect(fetchSalesOperations).toHaveBeenCalledTimes(1);
    expect(fetchSalesOperations.mock.calls[0][0]).toMatchObject({ ...dateRange(1), view: 'stores', page_size: 20 });
    expect(wrapper.text()).toContain('70.00'); expect(wrapper.text()).toContain('今日09:00同时段：待接入快照');
    expect(wrapper.text()).not.toContain('0.00 倍');
  });
  it('loads products only on explicit drill and opens evidence without a request', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    fetchSalesOperations.mockResolvedValue(response([{ ...row, product_id: 'P1', product_name: '床单', units_sold: 3, diagnosis: { status: 'suspected_decline', title: '下降待核查', steps: [{ label: '买家数', value: '缺少买家数，无法判断' }], missing: ['访客'] } }]));
    await wrapper.find('.text-button').trigger('click'); await flushPromises();
    expect(fetchSalesOperations.mock.calls[1][0]).toMatchObject({ view: 'products', store_id: '2', currency: 'PHP' });
    await wrapper.find('.reason-button').trigger('click');
    expect(wrapper.find('dialog').attributes('open')).toBeDefined();
    expect(wrapper.find('dialog').text()).toContain('缺少买家数'); expect(fetchSalesOperations).toHaveBeenCalledTimes(2);
    fetchSalesOperations.mockResolvedValue(response());
    await wrapper.find('.results-head button').trigger('click'); await flushPromises();
    expect(fetchSalesOperations.mock.calls[2][0]).toMatchObject({ view: 'stores', store_id: '' });
  });
  it('does not expose item drill without the SKU route grant', async () => {
    useAuthStore().currentUser.permissions = ['sales_management.view']; wrapper = mount(SalesOperations); await flushPromises();
    expect(wrapper.find('.text-button').attributes('disabled')).toBeDefined();
    await wrapper.find('.text-button').trigger('click'); expect(fetchSalesOperations).toHaveBeenCalledTimes(1);
  });
  it('restores exact item and all board scope, then returns to the original board scope', async () => {
    const range = dateRange(1);
    Object.assign(routeQuery, { view: 'operations', ...range, platform: 'shopee', region: 'PH', store_id: '2', currency: 'PHP', product_id: 'P-Exact', return_view: 'declines', return_date_from: range.date_from, return_date_to: range.date_to, return_platform: 'lazada', return_region: 'MY', return_store_id: '', return_currency: 'THB', return_metric: 'percent' });
    fetchSalesOperations.mockResolvedValue(response([{ ...row, product_id: 'P-Exact', product_name: '精确商品', units_sold: 1, diagnosis: { title: '需要核查', steps: [], missing: [] } }]));
    wrapper = mount(SalesOperations); await flushPromises();
    expect(fetchSalesOperations.mock.calls[0][0]).toMatchObject({ ...range, view: 'products', store_id: '2', platform: 'shopee', region: 'PH', currency: 'PHP', product_id: 'P-Exact' });
    expect(wrapper.find('dialog').attributes('open')).toBeDefined();
    expect(wrapper.text()).not.toContain('筛选已修改');
    await wrapper.find('.results-head button').trigger('click');
    expect(push).toHaveBeenCalledWith({ path: '/sales-management/realtime-board', query: { date_from: range.date_from, date_to: range.date_to, platform: 'lazada', region: 'MY', store_id: '', currency: 'THB', metric: 'percent', view: 'declines' } });
  });
  it('isolates route changes and prevents a stale product response from reopening its reason', async () => {
    const range = dateRange(1);
    Object.assign(routeQuery, { view: 'operations', ...range, region: 'PH', store_id: '2', currency: 'PHP', product_id: 'P1', return_view: 'declines' });
    let finishOld;
    fetchSalesOperations.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; })).mockResolvedValue(response([{ ...row, product_id: 'P2', product_name: '新商品', diagnosis: { title: '新商品原因', steps: [], missing: [] } }]));
    wrapper = mount(SalesOperations); await flushPromises();
    const staleSignal = fetchSalesOperations.mock.calls[0][1];
    routeQuery.product_id = 'P2'; await flushPromises();
    expect(staleSignal.aborted).toBe(true);
    finishOld(response([{ ...row, product_id: 'P1', product_name: '旧商品', diagnosis: { title: '旧商品原因', steps: [], missing: [] } }])); await flushPromises();
    expect(wrapper.find('dialog').text()).toContain('新商品原因'); expect(wrapper.find('dialog').text()).not.toContain('旧商品原因');
  });
  it('rejects array down-drill parameters without issuing a widened request', async () => {
    Object.assign(routeQuery, { view: 'operations', date_from: ['2026-10-22'], date_to: '2026-10-22', product_id: 'P-Exact' });
    wrapper = mount(SalesOperations); await flushPromises();
    expect(fetchSalesOperations).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('下钻参数无效');
  });
  it('drops stale responses and aborts old scope and unmounted reads', async () => {
    let first; fetchSalesOperations.mockImplementationOnce(() => new Promise(resolve => { first = resolve; }));
    wrapper = mount(SalesOperations); await flushPromises(); const signal = fetchSalesOperations.mock.calls[0][1];
    await wrapper.find('.quick button').trigger('click'); await flushPromises(); expect(signal.aborted).toBe(true);
    first(response([{ ...row, store_name: '旧范围' }])); await flushPromises(); expect(wrapper.text()).not.toContain('旧范围');
    const lastSignal = fetchSalesOperations.mock.calls.at(-1)[1]; wrapper.unmount(); wrapper = null; expect(lastSignal.aborted).toBe(true);
  });
  it('clears previous rows on a failed new request and preserves draft-only state', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    await wrapper.findAll('input')[0].setValue('2026-09-01'); expect(fetchSalesOperations).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain('筛选已修改');
    fetchSalesOperations.mockRejectedValue(new Error('读取失败')); await wrapper.find('.quick button').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('读取失败'); expect(wrapper.find('.table-scroll').exists()).toBe(false);
  });
  it('uses Beijing yesterday and does not coerce missing values to zero', () => {
    expect(dateRange(1, new Date('2026-10-23T01:00:00Z'))).toEqual({ date_from: '2026-10-22', date_to: '2026-10-22' });
    expect(amount(null)).toBe('—'); expect(amount(0)).toBe('0.00'); expect(percent(null)).toBe('—');
    expect(validRange({ date_from: '2026-01-01', date_to: '2026-03-01' })).toContain('31');
  });
});
