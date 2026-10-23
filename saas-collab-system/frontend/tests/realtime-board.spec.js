import { mount, flushPromises } from '@vue/test-utils';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import RealtimeBoard from '../src/views/sales-management/RealtimeBoard.vue';
import { useAuthStore } from '../src/stores/auth';
import { fetchRealtimeBoard } from '../src/api/realtimeBoard';
import { canAccessPath, menuItems } from '../src/router/menu';
import { readFileSync } from 'node:fs';

vi.mock('../src/api/realtimeBoard', () => ({ fetchRealtimeBoard: vi.fn(), fetchBoardFilters: vi.fn(async () => ({ success: true, data: { platforms: ['shopee'], stores: [] } })) }));
vi.mock('../src/api/salesManagement', () => ({ fetchSalesFilters: vi.fn(async () => ({ success: true, data: { platforms: ['shopee'], stores: [] } })) }));
const push = vi.fn();
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }));
const payload = (rate = null) => ({ success: true, data: { currency_groups: [{ currency: 'PHP', sales_amount: '1000.00', order_count: 12, valid_order_count: 10, units_sold: 20, ad_spend: rate === null ? null : '100', ad_rate: rate, ad_reason: rate === null ? '广告数据待齐' : '', trend: [{ date: '2026-10-22', sales_amount: '1000' }], store_ranking: [{ store_id: 2, store_name: '测试店铺', sales_amount: '1000' }], sku_ranking: [] }], notices: [] } });
let wrapper;
beforeEach(() => { vi.useFakeTimers(); setActivePinia(createPinia()); useAuthStore().currentUser = { user_type: 'internal', permissions: ['sales_management.view', 'sales_management.orders.view'] }; fetchRealtimeBoard.mockReset().mockResolvedValue(payload()); });
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.useRealTimers(); vi.clearAllMocks(); });

describe('实时数据大屏', () => {
  it('shows missing ads as unavailable, renders sales and keeps normal freshness hidden', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('实时数据大屏'); expect(wrapper.text()).toContain('1,000.00');
    expect(wrapper.text()).toContain('广告数据待齐'); expect(wrapper.text()).not.toContain('0.00%');
    expect(wrapper.text()).not.toContain('更新时间'); expect(wrapper.findAll('.kpi')).toHaveLength(5);
  });
  it('renders rate as percent and preserves filters in permitted drilldown', async () => {
    fetchRealtimeBoard.mockResolvedValue(payload(10)); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('10.00%');
    await wrapper.find('.trend-footer button').trigger('click');
    expect(push).toHaveBeenCalledWith(expect.objectContaining({ path: '/sales-management/orders', query: expect.objectContaining({ currency: 'PHP' }) }));
    expect(wrapper.text()).not.toContain('查看广告明细');
  });
  it('makes no overlapping poll and aborts/cleans up on leave', async () => {
    let resolve; fetchRealtimeBoard.mockImplementation(() => new Promise(done => { resolve = done; }));
    wrapper = mount(RealtimeBoard); await flushPromises(); const signal = fetchRealtimeBoard.mock.calls[0][1];
    await vi.advanceTimersByTimeAsync(180000); expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
    wrapper.unmount(); wrapper = null; expect(signal.aborted).toBe(true);
    resolve(payload()); await flushPromises(); await vi.advanceTimersByTimeAsync(180000); expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
  });
  it('pauses hidden tabs and resumes without a polling backlog', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises();
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(180000);
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false); document.dispatchEvent(new Event('visibilitychange')); await flushPromises();
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(2); hidden.mockRestore();
  });
  it('never retains a different filter result after a failed query', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises(); fetchRealtimeBoard.mockResolvedValue({ success: false, message: '暂不可用' });
    await wrapper.find('form').trigger('submit'); await flushPromises();
    expect(wrapper.text()).not.toContain('1,000.00'); expect(wrapper.text()).toContain('暂不可用');
  });
  it('removes a retained result after three consecutive refresh failures', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises();
    fetchRealtimeBoard.mockResolvedValue({ success: false, message: '数据暂不可用' });
    await vi.advanceTimersByTimeAsync(60000); await flushPromises();
    expect(wrapper.text()).toContain('当前保留上次结果');
    await vi.advanceTimersByTimeAsync(120000); await flushPromises();
    expect(wrapper.text()).not.toContain('1,000.00'); expect(wrapper.text()).toContain('数据暂不可用');
  });
  it('keeps exact SKU and advertising scope when drilling into detail', async () => {
    useAuthStore().currentUser.permissions.push('analytics.view');
    const response = payload(10);
    response.data.currency_groups[0].ad_store_ids = [2, 4];
    response.data.currency_groups[0].sku_ranking = [{ sku: 'A', name: '商品A', sales_amount: '1000', units_sold: 20 }];
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    await wrapper.find('.product-table button').trigger('click');
    expect(push).toHaveBeenLastCalledWith(expect.objectContaining({ query: expect.objectContaining({ sku: 'A', sku_exact: 'true', exclude_cancelled: 'true' }) }));
    await wrapper.find('.text-action').trigger('click');
    expect(push).toHaveBeenLastCalledWith(expect.objectContaining({ query: expect.objectContaining({ platform: 'shopee', store_ids: '2,4' }) }));
  });
  it('switches all five dimensions and metrics without extra requests', async () => {
    const response = payload(), group = response.data.currency_groups[0];
    const dimensions = ['store_spu', 'store_sku', 'product_spu', 'product_sku', 'category'];
    group.product_rankings = Object.fromEntries(dimensions.map(key => [key, {
      sales_amount: [{ key, name: key === 'category' ? '家居 / 床品 / 床笠' : `${key}销售额`, sales_amount: '120', units_sold: 3 }],
      units_sold: [{ key: `${key}-units`, name: `${key}销量`, sales_amount: '40', units_sold: 9 }]
    }]));
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    const tabs = wrapper.findAll('.product-dimensions button');
    expect(tabs.map(tab => tab.text())).toEqual(['店铺SPU', '店铺SKU', '商品SPU', '商品SKU', '商品分类']);
    expect(tabs[3].attributes('aria-pressed')).toBe('true');
    for (let index = 0; index < tabs.length; index++) {
      await wrapper.find('[aria-label="商品排行指标"]').setValue('sales_amount');
      await tabs[index].trigger('click');
      expect(wrapper.find('.product-table').text()).toContain(index === 4 ? '家居 / 床品 / 床笠' : `${dimensions[index]}销售额`);
      expect(wrapper.find('.product-table button').attributes('disabled')).toBeDefined();
      await wrapper.find('[aria-label="商品排行指标"]').setValue('units_sold');
      expect(wrapper.find('.product-table').text()).toContain(`${dimensions[index]}销量`);
    }
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
    expect(wrapper.find('.dimension-note').text()).toContain('系统维护的商品分类');
  });
  it('uses canonical SKU ID for system SKU drilldown and disables store aggregates', async () => {
    const response = payload(), group = response.data.currency_groups[0];
    group.product_rankings = { product_sku: { sales_amount: [
      { key: 'mapped', code: 'VAR-1', name: '平台规格', drill_internal_sku_id: 7, units_sold: 1, sales_amount: '100' },
      { key: 'aggregate', code: 'unmapped', name: '未映射', units_sold: 1, sales_amount: '50' }
    ] } };
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    const buttons = wrapper.findAll('.product-table button');
    await buttons[0].trigger('click');
    expect(push).toHaveBeenLastCalledWith(expect.objectContaining({ query: expect.objectContaining({ internal_sku_id: 7, exclude_cancelled: 'true' }) }));
    expect(buttons[1].attributes('disabled')).toBeDefined();
  });
  it('registers only a lazy menu entry, retaining action and internal-user gates', () => {
    const entry = menuItems.find(row => row.label === '销售管理').children.find(row => row.path === '/sales-management/realtime-board');
    expect(entry.label).toBe('实时数据大屏'); expect(entry.permissions).toEqual(['sales_management.view']);
    expect(canAccessPath({ user_type: 'external', permissions: ['sales_management.view'] }, entry.path)).toBe(false);
    expect(canAccessPath({ user_type: 'internal', permissions: [] }, entry.path)).toBe(false);
    expect(readFileSync('src/router/index.js', 'utf8')).toContain("const RealtimeBoard = () => import('../views/sales-management/RealtimeBoard.vue')");
  });
  it('switches rankings without network requests and uses whole currency sales for share', async () => {
    const response = payload(10), group = response.data.currency_groups[0];
    group.store_rankings = {
      sales_amount: [{ store_id: 2, store_name: '高销售店', sales_amount: '400', order_count: 2 }],
      order_count: [{ store_id: 3, store_name: '高订单店', sales_amount: '100', order_count: 20 }]
    };
    group.sku_rankings = {
      sales_amount: [{ sku: 'A', name: '高销售商品', sales_amount: '400', units_sold: 2 }],
      units_sold: [{ sku: 'B', name: '高销量商品', sales_amount: '100', units_sold: 20 }]
    };
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.store-ranking').text()).toContain('高销售店');
    await wrapper.find('[aria-label="店铺排行指标"]').setValue('order_count');
    expect(wrapper.find('.store-ranking').text()).toContain('高订单店');
    expect(wrapper.find('.store-ranking').text()).toContain('20 单');
    await wrapper.find('.store-ranking button').trigger('click');
    expect(push.mock.lastCall[0].query.exclude_cancelled).toBeUndefined();
    await wrapper.find('[aria-label="店铺排行指标"]').setValue('share');
    expect(wrapper.find('.store-ranking').text()).toContain('40.00%');
    await wrapper.find('[aria-label="商品排行指标"]').setValue('units_sold');
    expect(wrapper.find('.product-table').text()).toContain('高销量商品');
    expect(wrapper.find('.product-table').text()).not.toContain('高销售商品');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
  });
  it('distinguishes a measured zero stock from missing stock and shows shared warehouses', async () => {
    const response = payload();
    response.data.currency_groups[0].sku_ranking = [
      { sku: 'ZERO', name: '零库存商品', sales_amount: '100', units_sold: 2, inventory: { available_qty: 0, status: 'out', label: '已匹配仓库存为0', basis: '同站点已匹配仓共享库存', warehouses: [{ id: 1, name: '菲律宾共享仓', available_qty: 0 }], coverage_days: null, coverage_reason: '共享仓需求口径未齐，暂不计算' } },
      { sku: 'UNKNOWN', name: '未关联商品', sales_amount: '100', units_sold: 2, inventory: { available_qty: null, status: 'unmapped', label: '未关联库存', warehouses: [] } }
    ];
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    const rows = wrapper.findAll('.product-table tbody tr');
    expect(rows[0].find('.inventory-quantity').text()).toContain('0');
    expect(rows[1].find('.inventory-quantity').text()).toBe('—');
    expect(rows[0].text()).toContain('已匹配仓库存为0');
    expect(rows[0].text()).toContain('菲律宾共享仓');
    expect(rows[0].text()).toContain('共享仓需求口径未齐');
    expect(rows[1].text()).toContain('未关联库存');
    expect(wrapper.text()).toContain('不表示店铺独占');
  });
});
