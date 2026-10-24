import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import SalesOperations from '../src/views/sales-management/SalesOperations.vue';
import { useAuthStore } from '../src/stores/auth';
import { fetchSalesOperations } from '../src/api/salesOperations';
import { dateRange, amount, percent, validRange } from '../src/views/sales-management/salesOperations';
import { preferenceKey, readColumns, writeColumns } from '../src/views/sales-management/salesColumns';
vi.mock('../src/api/salesOperations', () => ({ fetchSalesOperations: vi.fn() }));
vi.mock('../src/api/realtimeBoard', () => ({ fetchBoardFilters: vi.fn(async () => ({ success: true, data: { stores: [] } })) }));
const push = vi.fn();
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => ({ query: {} }) }));
const row = { store_id: 2, store_name: '菲律宾店铺', country: 'PH', currency: 'PHP', sales_amount: '70', previous_sales_amount: '100', change_percent: '-30', ad_spend: null, roi: null, order_count: 2 };
const response = (rows = [row]) => ({ success: true, data: { rows, currency_groups: [{ ...row }], has_next: false } });
let wrapper;
beforeEach(() => { setActivePinia(createPinia()); useAuthStore().currentUser = { user_type: 'internal', permissions: ['sales_management.view','sales_management.skus.view'] }; fetchSalesOperations.mockReset().mockResolvedValue(response()); HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); }; HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); }; });
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.clearAllMocks(); });
describe('销售日常经营', () => {
  it('changes sorting on the server and resets pagination', async () => {
    fetchSalesOperations.mockResolvedValue({ ...response(), data: { ...response().data, has_next: true } });
    wrapper = mount(SalesOperations); await flushPromises();
    await wrapper.findAll('.pagination button')[1].trigger('click'); await flushPromises();
    expect(fetchSalesOperations.mock.calls.at(-1)[0].page).toBe(2);
    await wrapper.find('.list-tools select').setValue('change_asc'); await flushPromises();
    expect(fetchSalesOperations.mock.calls.at(-1)[0]).toMatchObject({ page: 1, sort: 'change_asc', status: 'all' });
  });
  it('selects columns without queries and keeps identity and current GMV visible', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    const change = wrapper.findAll('.column-options label').find(label => label.text() === '变化率');
    await change.find('input').setValue(false);
    expect(wrapper.findAll('th').map(th => th.text())).not.toContain('变化率');
    expect(wrapper.findAll('th').map(th => th.text())).toContain('GMV / 币种');
    expect(fetchSalesOperations).toHaveBeenCalledTimes(1);
    await wrapper.find('.column-options button').trigger('click');
    expect(wrapper.findAll('th').map(th => th.text())).toContain('变化率');
  });
  it('filters anomalies on the server only after shop drill', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    await wrapper.find('.text-button').trigger('click'); await flushPromises();
    await wrapper.findAll('.list-tools select')[1].setValue('unobserved'); await flushPromises();
    expect(fetchSalesOperations.mock.calls.at(-1)[0]).toMatchObject({ view: 'products', store_id: '2', page: 1, status: 'unobserved' });
  });
  it('keeps only whitelisted column names in user-specific preferences', () => {
    const a = preferenceKey({ id: 4, tenant_id: 1 }), b = preferenceKey({ id: 5, tenant_id: 1 });
    expect(a).not.toBe(b);
    localStorage.setItem(a, JSON.stringify({ stores: ['change','evil','all_sales_rows'], raw: ['secret'] }));
    expect(readColumns(localStorage, a, 'stores')).toEqual(['change']);
    writeColumns(localStorage, a, 'stores', ['change', 'injected']);
    expect(localStorage.getItem(a)).not.toContain('secret');
    expect(localStorage.getItem(a)).not.toContain('injected');
    expect(readColumns(localStorage, b, 'stores')).toContain('previous');
    localStorage.removeItem(a);
  });
  it('preserves currency choices after narrowing one currency', async () => {
    fetchSalesOperations.mockResolvedValueOnce({ success: true, data: { ...response().data, currency_groups: [{ currency: 'MYR' }, { currency: 'PHP' }] } });
    wrapper = mount(SalesOperations); await flushPromises();
    await wrapper.find('.currency-bar select').setValue('PHP'); await flushPromises();
    expect(wrapper.findAll('.currency-bar option').map(o => o.attributes('value'))).toEqual(['', 'MYR', 'PHP']);
    await wrapper.find('.currency-bar select').setValue('MYR'); await flushPromises();
    expect(fetchSalesOperations.mock.calls.at(-1)[0].currency).toBe('MYR');
  });
  it('defaults to yesterday with one summary request and no polling', async () => {
    wrapper = mount(SalesOperations); await flushPromises();
    expect(fetchSalesOperations).toHaveBeenCalledTimes(1);
    expect(fetchSalesOperations.mock.calls[0][0]).toMatchObject({ ...dateRange(1), view: 'stores', page_size: 20 });
    expect(wrapper.text()).toContain('70.00'); expect(wrapper.text()).toContain('今日09:00同时段：查看快照');
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
