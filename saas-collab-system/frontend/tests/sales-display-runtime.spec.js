import { mount, flushPromises } from '@vue/test-utils';
import { computed } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ fetchSalesPage: vi.fn(), fetchSalesFilters: vi.fn(), fetchSalesOrderDetail: vi.fn(), createSalesExport: vi.fn() }));
const priceApi = vi.hoisted(() => ({ fetchPrices: vi.fn() }));
vi.mock('../src/api/salesManagement', () => api);
vi.mock('../src/api/pricing', () => priceApi);
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: { permissions: [] } }) }));
import SalesWorkspace from '../src/views/sales-management/SalesWorkspace.vue';
import PriceList from '../src/views/pricing/PriceList.vue';

const stubs = {
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-button': { template: '<button><slot /></button>' },
  'el-select': { template: '<select><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-date-picker': true, 'el-input': true, 'el-pagination': true,
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-table': { props: ['data'], provide() { return { rows: computed(() => this.data) }; }, template: '<div><slot /></div>' },
  'el-table-column': { props: ['label'], inject: ['rows'], template: '<section>{{ label }}<slot v-for="row in rows" :row="row" /></section>' },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' },
  'el-drawer': { props: ['modelValue', 'title'], template: '<aside v-if="modelValue">{{ title }}<slot /></aside>' },
  'el-dialog': true
};
const render = mode => mount(SalesWorkspace, { props: { mode }, global: { stubs, directives: { loading: () => {} } } });
beforeEach(() => {
  vi.clearAllMocks();
  api.fetchSalesFilters.mockResolvedValue({ success: true, data: {} });
  api.fetchSalesPage.mockResolvedValue({ success: true, data: { results: [], quality: { checked_rows: 0, score: 100 } } });
});

describe('销售页面展示验收', () => {
  it('shows no-data guidance instead of asking for metrics on an empty SKU report', async () => {
    const wrapper = render('skus'); await flushPromises();
    expect(wrapper.text()).toContain('当前币种暂无趋势数据');
    expect(wrapper.text()).not.toContain('请选择至少一个趋势指标');
    wrapper.unmount();
  });
  it('moves overview dates to one summary toolbar across currencies', async () => {
    api.fetchSalesPage.mockResolvedValue({ success: true, data: { currency_groups: [{currency:'PHP',metrics:[]},{currency:'THB',metrics:[]}] } });
    const wrapper = render('overview'); await flushPromises();
    expect(wrapper.find('.sales-filters .quick-dates').exists()).toBe(false);
    expect(wrapper.find('.sales-filters el-date-picker-stub').exists()).toBe(false);
    expect(wrapper.findAll('.summary-dates')).toHaveLength(1);
    expect(wrapper.find('.analysis-tabs').exists()).toBe(false);
    await wrapper.findAll('.summary-dates button')[1].trigger('click'); await flushPromises();
    expect(api.fetchSalesPage.mock.lastCall[1]).toMatchObject({date_from:wrapper.vm.query.date_range[0],date_to:wrapper.vm.query.date_range[1]});
    expect(wrapper.vm.hasUnappliedFilters).toBe(false);
    wrapper.unmount();
  });
  it('separates order report from SKU report and keeps SKU sorting server-backed', async () => {
    const overview = render('overview'); await flushPromises();
    expect(overview.text()).toContain('订单汇总明细');
    expect(overview.text()).not.toContain('SKU 销量明细');
    overview.unmount();
    const wrapper = render('skus'); await flushPromises();
    expect(wrapper.text()).toContain('按店铺 SKU 汇总');
    expect(wrapper.text()).toContain('产品销量信息');
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('skus', expect.objectContaining({ report: 'true', grouping: 'store' }));
    wrapper.vm.changeSkuGrouping('product'); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('skus', expect.objectContaining({ grouping: 'product', page: 1 }));
    wrapper.vm.query.sku = 'DRAFT';
    wrapper.vm.sortSkus({ prop: 'units_sold', order: 'descending' }); await flushPromises();
    expect(api.fetchSalesPage.mock.lastCall[1]).toMatchObject({ grouping: 'product', ordering: '-units_sold' });
    expect(api.fetchSalesPage.mock.lastCall[1]).not.toHaveProperty('sku');
    wrapper.vm.applyFilters(); await flushPromises();
    expect(api.fetchSalesPage.mock.lastCall[1].sku).toBe('DRAFT');
    wrapper.unmount();
  });
  it.each(['overview', 'stores'])('supports multiple platforms and stores in %s without changing applied filters', async mode => {
    api.fetchSalesFilters.mockResolvedValue({ success: true, data: { platforms: ['shopee', 'tiktok'], stores: [
      { id: 1, name: 'A', platform: 'shopee', region: 'PH' }, { id: 2, name: 'B', platform: 'tiktok', region: 'PH' }
    ] } });
    const wrapper = render(mode); await flushPromises();
    expect(wrapper.vm.query.platform).toEqual([]);
    expect(wrapper.vm.query.store_id).toEqual([]);
    wrapper.vm.query.platform = ['tiktok', 'shopee'];
    wrapper.vm.query.store_id = [2, 1];
    wrapper.vm.applyFilters(); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith(mode, expect.objectContaining({ platforms: 'shopee,tiktok', store_ids: '1,2' }));
    wrapper.vm.query.platform.splice(0, 1);
    wrapper.vm.onPlatformChange();
    expect(wrapper.vm.query.store_id).toEqual([1]);
    expect(wrapper.vm.hasUnappliedFilters).toBe(true);
    await wrapper.vm.loadData(true);
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith(mode, expect.objectContaining({ platforms: 'shopee,tiktok', store_ids: '1,2' }));
    api.createSalesExport.mockResolvedValue({ success: true, data: {} });
    await wrapper.vm.submitExport(); await flushPromises();
    expect(api.createSalesExport.mock.calls[0][0].filters).toMatchObject({ platforms: ['shopee', 'tiktok'], store_ids: [1, 2] });
    wrapper.vm.query.platform = []; wrapper.vm.query.store_id = [];
    wrapper.vm.applyFilters(); await flushPromises();
    const params = api.fetchSalesPage.mock.calls.at(-1)[1];
    expect(params).not.toHaveProperty('platforms');
    expect(params).not.toHaveProperty('store_ids');
    wrapper.unmount();
  });
  it.each(['overview', 'orders', 'returns', 'stores', 'skus', 'exports', 'data-quality'])('renders %s with correct empty and quality states', async mode => {
    const wrapper = render(mode);
    await flushPromises();
    expect(wrapper.text()).not.toContain('100 / 100');
    expect(wrapper.text()).not.toContain('[object Object]');
    if (mode !== 'exports') expect(wrapper.text()).toContain('尚未评估');
    else expect(wrapper.text()).toContain('任务列表已读取');
    wrapper.unmount();
  });
  it('renders real currency-object trends and no invented anomaly success', async () => {
    api.fetchSalesPage.mockResolvedValue({ success: true, data: {
      trend: [{ date: '2026-09-10', net_sales: { PHP: '0', THB: '-125.5' } }],
      currency_groups: [{ currency: 'PHP', metrics: [{ code: 'gross_sales', label: 'Sales', value: '12345.5', unit: 'PHP' }, {code:'net_sales',label:'净销售额',value:'0',unit:'PHP'}] }, {currency:'THB',metrics:[{code:'net_sales',label:'净销售额',value:'-125.5',unit:'THB'}]}]
    } });
    const wrapper = render('overview'); await flushPromises();
    expect(wrapper.text()).toContain('12,345.50');
    expect(wrapper.text()).toContain('总览接口未提供异常明细');
    expect(wrapper.find('svg').attributes('aria-label')).toContain('PHP');
    expect(wrapper.find('circle title').text()).toContain('0.00');
    expect(wrapper.findAll('.overview-analysis')).toHaveLength(2);
    expect(wrapper.findAll('svg')[1].attributes('aria-label')).toContain('THB');
    expect(wrapper.findAll('.overview-analysis')[1].text()).toContain('THB');
    expect(wrapper.findAll('circle title').some(node => node.text().includes('-125.50'))).toBe(true);
    const ids = wrapper.findAll('[role=tabpanel]').map(node => node.attributes('id'));
    expect(new Set(ids).size).toBe(ids.length);
    wrapper.unmount();
  });
  it('formats order list and detail consistently and leaves identifiers intact', async () => {
    const row = { id: 1, external_order_id: '001234567890123456789', platform: 'tiktok', normalized_status: 'cancelled', order_total_amount: '12345.6789', created_at_utc: '2026-09-11T02:00:00Z', currency: 'PHP' };
    api.fetchSalesPage.mockResolvedValue({ success: true, data: { results: [row], count: 1 } });
    api.fetchSalesOrderDetail.mockResolvedValue({ success: true, data: { ...row, items: [{ seller_sku: 'SKU-TEST', internal_sku: null, quantity: 0, line_total_amount: '0.0000' }] } });
    const wrapper = render('orders'); await flushPromises();
    expect(wrapper.text()).toContain('001234567890123456789');
    expect(wrapper.text()).toContain('已取消');
    expect(wrapper.text()).toContain('12,345.68');
    await wrapper.vm.selectRow(row); await flushPromises();
    expect(wrapper.find('aside').text()).toContain('原始金额：12345.6789');
    expect(wrapper.find('aside').text()).toContain('未关联');
    wrapper.unmount();
  });
  it('keeps overview filters server-backed and only queries on filter submission', async () => {
    const wrapper = render('overview'); await flushPromises();
    expect(wrapper.vm.resolvedFilters.map(filter => filter.key)).toEqual(['platform', 'store_id', 'currency']);
    Object.assign(wrapper.vm.query, { platform: 'tiktok', store_id: 67, currency: 'PHP', date_range: ['2026-08-01', '2026-08-31'] });
    wrapper.vm.applyFilters(); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('overview', expect.objectContaining({ platform: 'tiktok', store_id: 67, currency: 'PHP', date_from: '2026-08-01', date_to: '2026-08-31' }));
    expect(api.createSalesExport).not.toHaveBeenCalled();
    expect(api.fetchSalesOrderDetail).not.toHaveBeenCalled();
    wrapper.vm.applyQuickRange(7); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('overview', expect.objectContaining({ platform: 'tiktok', store_id: 67, currency: 'PHP', date_from: wrapper.vm.query.date_range[0], date_to: wrapper.vm.query.date_range[1] }));
    wrapper.unmount();
  });
  it('shows provided sync source fields but not credential metadata', async () => {
    api.fetchSalesPage.mockResolvedValue({ success: true, data: { sources: [{ id: 5, resource: 'sales_order', run_status: 'failed', fetched_count: 1234, credential_mask: 'DO-NOT-DISPLAY' }] } });
    const wrapper = render('data-quality'); await flushPromises();
    expect(wrapper.text()).toContain('销售订单');
    expect(wrapper.text()).toContain('1,234');
    expect(wrapper.text()).not.toContain('DO-NOT-DISPLAY');
    wrapper.unmount();
  });
  it.each(['overview', 'stores'])('keeps %s queries, exports and pagination on the applied conditions', async mode => {
    const wrapper = render(mode); await flushPromises();
    expect(wrapper.vm.isQuickRange(30)).toBe(true);
    const original = { ...api.fetchSalesPage.mock.lastCall[1] };
    const calls = api.fetchSalesPage.mock.calls.length;
    wrapper.vm.query.platform = 'tiktok';
    wrapper.vm.onPlatformChange(); await flushPromises();
    wrapper.vm.query.currency = 'THB';
    expect(api.fetchSalesPage.mock.calls.length).toBe(calls);
    expect(wrapper.vm.hasUnappliedFilters).toBe(true);
    expect(wrapper.text()).toContain('筛选已修改，请点击查询');
    await wrapper.vm.loadData(true); await flushPromises();
    expect(api.fetchSalesPage.mock.lastCall[1]).toMatchObject(original);
    api.createSalesExport.mockResolvedValueOnce({ success: true });
    await wrapper.vm.submitExport(); await flushPromises();
    const exported = api.createSalesExport.mock.lastCall[0].filters;
    expect(exported).not.toHaveProperty('currency');
    expect(exported).not.toHaveProperty('platform');
    expect(exported).not.toHaveProperty('page');
    expect(exported.date_from).toBe(original.date_from);
    wrapper.vm.applyFilters(); await flushPromises();
    expect(api.fetchSalesPage.mock.lastCall[1]).toMatchObject({ platform: 'tiktok', currency: 'THB' });
    expect(wrapper.vm.hasUnappliedFilters).toBe(false);
    wrapper.unmount();
  });
  it('renders store report controls and sends sorting to the full-result API', async () => {
    api.fetchSalesPage.mockResolvedValue({ success: true, data: {
      results: [{ store_name: 'TEST SHOP', currency: 'PHP', gross_sales: '100', valid_order_count: 2 }], count: 1,
      currency_groups: [{ currency: 'PHP', metrics: [{ code: 'gross_sales', value: '100', unit: 'PHP', label: '非取消订单销售额', definition: '非取消订单的订单总金额' }] }],
      trend: [{ date: '2026-09-10', gross_sales: { PHP: '100' } }]
    } });
    const wrapper = render('stores'); await flushPromises();
    expect(wrapper.text()).toContain('店铺概览');
    expect(wrapper.text()).toContain('汇总明细');
    expect(wrapper.text()).toContain('非取消订单的订单总金额');
    expect(wrapper.findAll('.performance-strip')).toHaveLength(1);
    expect(wrapper.vm.displayedColumns.some(column => column.prop === 'store_code')).toBe(false);
    wrapper.vm.storeColumns.push('store_code');
    await flushPromises();
    expect(wrapper.vm.displayedColumns.some(column => column.prop === 'store_code')).toBe(true);
    wrapper.vm.page = 3;
    wrapper.vm.sortStores({ prop: 'gross_sales', order: 'descending' }); await flushPromises();
    expect(api.fetchSalesPage).toHaveBeenLastCalledWith('stores', expect.objectContaining({ page: 1, ordering: '-gross_sales' }));
    wrapper.vm.sortStores({ prop: 'gross_sales', order: null }); await flushPromises();
    expect(api.fetchSalesPage.mock.lastCall[1]).not.toHaveProperty('ordering');
    wrapper.vm.openExportDialog();
    expect(wrapper.vm.exportForm.export_type).toBe('store_sales');
    expect(api.createSalesExport).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('clears stale numbers on errors and ignores a delayed old failure', async () => {
    const wrapper = render('overview'); await flushPromises();
    let rejectOld;
    api.fetchSalesPage.mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
    const old = wrapper.vm.loadData();
    api.fetchSalesPage.mockResolvedValueOnce({ success: true, data: { order_daily: [{ date: '2026-08-17', currency: 'PHP', gross_sales: '123456.78' }], count: 1 } });
    await wrapper.vm.loadData(); rejectOld(new Error('old failure')); await old; await flushPromises();
    expect(wrapper.text()).toContain('123,456.78');
    expect(wrapper.text()).not.toContain('old failure');
    api.fetchSalesPage.mockResolvedValueOnce({ success: false, message: '测试读取失败' });
    await wrapper.vm.loadData(); await flushPromises();
    expect(wrapper.text()).not.toContain('123,456.78');
    expect(wrapper.text()).toContain('读取失败');
    wrapper.unmount();
  });
  it('shows pricing as pending and keeps writes disabled', async () => {
    priceApi.fetchPrices.mockResolvedValue({ success: true, data: { api_status: 'pending', items: [] } });
    const wrapper = mount(PriceList, { global: { stubs, directives: { loading: () => {} } } }); await flushPromises();
    expect(wrapper.text()).toContain('待接入');
    expect(wrapper.text()).not.toContain('暂无 Mock 数据');
    expect(wrapper.findAll('button').every(button => button.attributes('disabled') !== undefined)).toBe(true);
    wrapper.unmount();
  });
});
