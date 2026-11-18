import { mount, flushPromises } from '@vue/test-utils';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { reactive } from 'vue';
import RealtimeBoard from '../src/views/sales-management/RealtimeBoard.vue';
import { useAuthStore } from '../src/stores/auth';
import { fetchRealtimeBoard, fetchBoardFilters, fetchBoardDeclines } from '../src/api/realtimeBoard';
import { canAccessPath, menuItems } from '../src/router/menu';
import { readFileSync } from 'node:fs';

vi.mock('../src/api/realtimeBoard', () => ({ fetchRealtimeBoard: vi.fn(), fetchBoardDeclines: vi.fn(async () => ({ success: true, data: { rows: [], filters: {} } })), fetchBoardFilters: vi.fn(async () => ({ success: true, data: { platforms: ['shopee'], stores: [] } })) }));
vi.mock('../src/api/salesManagement', () => ({ fetchSalesFilters: vi.fn(async () => ({ success: true, data: { platforms: ['shopee'], stores: [] } })) }));
const push = vi.fn();
const routeQuery = reactive({});
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => ({ query: routeQuery }) }));
const payload = (rate = null) => ({ success: true, data: { cny_summary: { sales_amount: null, ad_spend: null, roi: null, roi_sales_scope: '可比店铺 GMV', rate_dates: [], excluded_currencies: ['PHP'], ad_partial: true }, currency_groups: [{ currency: 'PHP', sales_amount: '1000.00', order_count: 12, valid_order_count: 10, units_sold: 20, ad_spend: rate === null ? null : '100', ad_clicks: null, ad_clicks_partial: false, ad_rate: rate, ad_reason: rate === null ? '广告数据待齐' : '', trend: [{ date: '2026-10-22', sales_amount: '1000' }], store_ranking: [{ store_id: 2, store_name: '测试店铺', sales_amount: '1000' }], sku_ranking: [] }], notices: [] } });
let wrapper;
beforeEach(() => { Object.keys(routeQuery).forEach(key => delete routeQuery[key]); vi.useFakeTimers(); setActivePinia(createPinia()); useAuthStore().currentUser = { user_type: 'internal', permissions: ['sales_management.view', 'sales_management.orders.view'] }; fetchRealtimeBoard.mockReset().mockResolvedValue(payload()); });
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.useRealTimers(); vi.clearAllMocks(); });

describe('实时数据大屏', () => {
  it('labels mixed advertising ROI by its actual scope and keeps clicks Shopee-only', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], {
      ad_spend: '100', store_roi: '10', ad_rate_platform_scope: 'Shopee 与 TikTok GMV Max 授权店铺',
      ad_status: 'estimated', ad_reason: '存在在途数据',
    });
    fetchRealtimeBoard.mockResolvedValue(response);
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('Shopee 与 TikTok GMV Max 授权店铺');
    expect(wrapper.text()).toContain('销售额 ÷ 广告消耗');
    expect(wrapper.text()).toContain('10.00 倍');
    expect(wrapper.text()).toContain('已授权 Shopee 店铺 ·');
    expect(wrapper.text()).toContain('存在在途数据');
  });
  it('shows metric-specific store share, units ranking and valid-order average value', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], {
      sales_amount:'1000',valid_order_count:4,order_count:5,units_sold:10,
      store_rankings:{
        sales_amount:[{store_id:1,store_name:'甲店',sales_amount:'250',order_count:2,units_sold:3,store_roi:'2.345',roi_reason:'部分数据'}],
        order_count:[{store_id:1,store_name:'甲店',sales_amount:'250',order_count:2,units_sold:3,store_roi:'2.345',roi_reason:'部分数据'}],
        units_sold:[{store_id:2,store_name:'乙店',sales_amount:'750',order_count:3,units_sold:7}],
      },
    });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper=mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.store-share').text()).toBe('25.00%');
    expect(wrapper.find('.store-roi').text()).toBe('ROI 2.35 倍');
    expect(wrapper.find('.store-roi').attributes('title')).toBe('部分数据');
    expect(wrapper.findAll('.kpi').find(x=>x.text().includes('客单价')).text()).toContain('250.00');
    const select=wrapper.find('[aria-label="店铺排行指标"]');
    await select.setValue('order_count');
    expect(wrapper.find('.store-share').text()).toBe('40.00%');
    await select.setValue('units_sold');
    expect(wrapper.find('.store-ranking').text()).toContain('乙店');
    expect(wrapper.find('.store-ranking').text()).toContain('7 件');
    expect(wrapper.find('.store-share').text()).toBe('70.00%');
    expect(wrapper.find('.donut-center').text()).toContain('件');
  });
  it('does not invent average order value or share when denominator is zero', async () => {
    const response=payload();Object.assign(response.data.currency_groups[0], {sales_amount:'0',valid_order_count:0});
    fetchRealtimeBoard.mockResolvedValue(response); wrapper=mount(RealtimeBoard);await flushPromises();
    expect(wrapper.findAll('.kpi').find(x=>x.text().includes('客单价')).text()).toContain('—');
    expect(wrapper.find('.store-share').text()).toBe('—');
  });

  it('requests CNY by default and reloads all stores in the selected display currency', async () => {
    const response = payload();
    response.data.display_currency = 'CNY';
    response.data.available_display_currencies = ['CNY', 'PHP'];
    response.data.currency_groups[0].currency = 'CNY';
    fetchRealtimeBoard.mockResolvedValueOnce(response);
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    expect(fetchRealtimeBoard.mock.calls[0][0].display_currency).toBe('CNY');
    const selected = payload();
    selected.data.display_currency = 'PHP';
    selected.data.available_display_currencies = ['CNY', 'PHP'];
    fetchRealtimeBoard.mockResolvedValueOnce(selected);
    const picker = wrapper.findAll('select').find(select => select.findAll('option').some(option => option.text() === 'CNY'));
    await picker.setValue('PHP');
    await flushPromises();
    expect(fetchRealtimeBoard.mock.calls[1][0].display_currency).toBe('PHP');
    expect(fetchRealtimeBoard.mock.calls[1][0].currency).toBeUndefined();
  });
  it('switches platform advertising locally and keeps two decimal ROI', async () => {
    const response = payload();
    response.data.currency_groups[0].advertising_platforms = [
      { platform: 'shopee', label: 'Shopee', ad_spend: '10', sales_amount: '123', store_roi: '12.3', clicks: 5, partial: false },
      { platform: 'tiktok', label: 'TikTok', ad_spend: '20', sales_amount: '100', store_roi: '5', clicks: null, partial: true },
    ];
    fetchRealtimeBoard.mockResolvedValue(response);
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    expect(wrapper.find('.platform-advertising').text()).toContain('12.30 倍');
    expect(wrapper.find('.ad-collection-note').text()).toContain('不使用昨日费用补今日');
    expect(wrapper.find('.platform-advertising').text()).toContain('T+1 采集');
    expect(wrapper.find('.platform-advertising').text()).toContain('“未入库”不代表零花费');
    const tabs = wrapper.findAll('.platform-tabs button');
    await tabs.find(button => button.text() === 'TikTok').trigger('click');
    const panel = wrapper.find('.platform-advertising');
    expect(panel.text()).toContain('5.00 倍');
    expect(panel.text()).toContain('有在途数据');
    expect(panel.find('.platform-advertising-row').text()).not.toContain('广告点击量');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
  });
  it('shows hourly advertising as observed only and leaves missing hours absent', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], { ad_spend: '99', hourly_advertising: {
      date: '2026-10-22', observed_expense: '0', observed_clicks: 0, observed_store_count: 1,
      observed_store_hour_count: 1, timezones: ['Asia/Manila'], coverage_status: 'observed_only_unknown',
      hours: [{ hour: 0, label: '00:00', expense: '0', clicks: 0, observed_store_count: 1 }],
    } });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('小时广告');
    expect(wrapper.text()).toContain('不代表全天完整');
    expect(wrapper.text()).toContain('日报广告消耗独立展示');
    expect(wrapper.text()).toContain('00:00');
    expect(wrapper.text()).not.toContain('01:00');
  });
  it('shows unavailable CNY totals and excluded currencies without rendering zero', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('人民币汇总');
    expect(wrapper.text()).toContain('未换算币种：PHP');
    expect(wrapper.text()).toContain('参考汇率日期：暂无');
    expect(wrapper.text()).not.toContain('0.00 CNY');
  });
  it('keeps the store donut valid when decimal amounts differ only by floating point noise', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], {
      sales_amount: '0.30',
      store_ranking: [
        { store_id: 1, store_name: '甲店', sales_amount: '0.10' },
        { store_id: 2, store_name: '乙店', sales_amount: '0.20' },
      ],
    });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    const donut = wrapper.find('.store-donut');
    expect(donut.attributes('aria-label')).toContain('0.3');
    expect(donut.findAll('.donut-slice')).toHaveLength(2);
    expect(wrapper.text()).toContain('TOP 9 店铺占当前范围：100.0%');
    expect(wrapper.text()).not.toContain('无法计算（范围包含净额调整）');
  });
  it('formats converted advertising money to two decimals in every detail panel', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], {
      ad_rate_sales_amount: '138644.281684792742',
      hourly_advertising: { date:'2026-11-16', observed_expense:'17554.452055662546', hours:[{hour:0,label:'00:00',expense:'1067.522756379696',clicks:2240,observed_store_count:17}] },
    });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.hourly-ad-panel').text()).toContain('17,554.45');
    expect(wrapper.find('.hourly-ad-panel').text()).toContain('1,067.52');
    expect(wrapper.find('.ad-panel').text()).toContain('138,644.28');
    expect(wrapper.text()).not.toContain('281684792742');
  });
  it('mounts the real hourly chart with yesterday and cumulative data', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], { trend_granularity: 'hour', trend: [{date:'01:00',sales_amount:'12',order_count:2}], previous_hourly_trend: [{date:'01:00',sales_amount:'5',order_count:1}], recent_trend: [] });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.hourly-chart').exists()).toBe(true);
    expect(wrapper.findAll('.hourly-chart rect:not([fill="transparent"])')).toHaveLength(2);
    expect(wrapper.text()).toContain('今日累计：12 PHP');
    await wrapper.find('.hourly-chart rect[tabindex]').trigger('pointerenter');
    expect(wrapper.find('.chart-tooltip').text()).toContain('00:00');
    await wrapper.find('.hourly-chart svg').trigger('pointerleave');
    expect(wrapper.find('.chart-tooltip').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('import BoardHourlyTrend');
  });
  it('shows unmapped platform identities and carries them to the mapping page', async () => {
    useAuthStore().currentUser.permissions.push('listings.product_detail.view', 'integrations.product_mapping.view', 'menu.listings.products_platform_details.view');
    const data=payload();
    data.data.currency_groups[0].sku_ranking=[{key:'unmapped:1',name:'Platform item',mapping_status:'unmapped',store_id:2,store_name:'Store A',platform_product_id:'P123',platform_variant_id:'V456'}];
    fetchRealtimeBoard.mockResolvedValue(data);
    wrapper=mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('平台商品ID P123');
    const button=wrapper.findAll('button').find(b=>b.text().includes('补全映射'));
    expect(button).toBeDefined();
    await button.trigger('click');
    expect(push).toHaveBeenCalledWith({path:'/products/platform-details',query:{store_id:'2',variant_id:'V456',search:'P123'}});
  });
  it('keeps mapped product rows visible with an omitted mapping notice', async () => {
    const data = payload();
    data.data.currency_groups[0].product_mapping_note = '系统商品排行仅统计已映射商品，部分数据尚未映射。';
    fetchRealtimeBoard.mockResolvedValue(data);
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('系统商品排行仅统计已映射商品');
    expect(wrapper.text()).toContain('1,000.00');
  });
  it('shows missing ads as unavailable, renders sales and keeps normal freshness hidden', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('实时数据大屏'); expect(wrapper.text()).toContain('1,000.00');
    expect(wrapper.text()).toContain('广告数据待齐'); expect(wrapper.findAll('.kpi').find(x=>x.text().includes('广告费率')).text()).not.toContain('0.00%');
    expect(wrapper.text()).not.toContain('更新时间'); expect(wrapper.findAll('.kpi')).toHaveLength(6);
    expect(wrapper.text()).toContain('广告花费尚未拉取：广告数据待齐');
    expect(wrapper.text()).toContain('广告点击量'); expect(wrapper.text()).toContain('暂无已入库点击数据');
    expect(wrapper.text()).toContain('广告数据待齐');
  });
  it('renders observed ad clicks as available data and preserves zero', async () => {
    const response = payload(); Object.assign(response.data.currency_groups[0], { ad_clicks: 0, ad_clicks_observed_count: 1, ad_clicks_partial: true });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('广告点击量'); expect(wrapper.text()).toContain('当前已入库，部分数据');
    expect(wrapper.text()).toContain('0'); expect(wrapper.text()).not.toContain('暂无已入库点击数据');
  });
  it('renders rate as percent and preserves filters in permitted drilldown', async () => {
    fetchRealtimeBoard.mockResolvedValue(payload(10)); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('10.00%');
    await wrapper.find('.trend-footer button').trigger('click');
    expect(push).toHaveBeenCalledWith(expect.objectContaining({ path: '/sales-management/orders', query: expect.objectContaining({ currency: 'PHP' }) }));
    expect(wrapper.text()).not.toContain('查看广告明细');
  });
  it('shows estimated partial advertising coverage beside the returned rate and ROI', async () => {
    const response = payload(5);
    Object.assign(response.data.currency_groups[0], {
      ad_spend: '50', store_roi: '20', ad_status: 'estimated',
      ad_reason: '按当前已入库广告数据暂估；部分费用字段尚未拉取，补采后可能调整。'
    });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('5.00%');
    expect(wrapper.text()).toContain('20.00 倍');
    expect(wrapper.text()).toContain('暂估');
    expect(wrapper.text()).toContain('补采后可能调整');
    expect(wrapper.text()).toContain('暂估：有在途数据，后续同步后将更新。');
  });
  it('shows zero ad spend as not computable and accepts a numeric zero ROI', async () => {
    const response = payload(0);
    Object.assign(response.data.currency_groups[0], { ad_spend: '0', store_roi: null, ad_reason: '无广告消耗' });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('广告花费为0，无法计算ROI');
    response.data.currency_groups[0].store_roi = '0';
    fetchRealtimeBoard.mockResolvedValue(response);
    await wrapper.find('form').trigger('submit'); await flushPromises();
    expect(wrapper.text()).toContain('0.00 倍');
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
  it('retains the current scope after repeated timeouts', async () => {
    wrapper = mount(RealtimeBoard); await flushPromises();
    fetchRealtimeBoard.mockRejectedValue(new Error('timeout of 10000ms exceeded'));
    await vi.advanceTimersByTimeAsync(60000); await flushPromises();
    expect(wrapper.text()).toContain('当前保留上次结果');
    await vi.advanceTimersByTimeAsync(120000); await flushPromises();
    expect(wrapper.text()).toContain('1,000.00'); expect(wrapper.text()).toContain('当前保留上次结果');
  });
  it('shows sales while the inventory request is pending', async () => {
    const summary = payload();
    summary.data.inventory_deferred = true;
    summary.data.currency_groups[0].sku_ranking = [{ sku: 'A', name: '测试SKU', sales_amount: '1000', units_sold: 2 }];
    let finishInventory;
    fetchRealtimeBoard.mockResolvedValueOnce(summary)
      .mockImplementationOnce(() => new Promise(resolve => { finishInventory = resolve; }));
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    expect(wrapper.text()).toContain('库存加载中');
    expect(fetchRealtimeBoard.mock.calls[0][0].defer_inventory).toBe(1);
    expect(fetchRealtimeBoard.mock.calls[1][0].defer_inventory).toBeUndefined();
    expect(fetchRealtimeBoard.mock.calls[1][0].inventory_only).toBe(1);
    finishInventory({ success: true, data: { inventory_only: true, inventory_by_currency: {
      PHP: { legacy: { sales_amount: { A: { available_qty: 73, status: 'available', label: '库存已匹配' } } } },
    } } });
    await flushPromises();
    expect(wrapper.text()).not.toContain('库存加载中');
    expect(wrapper.find('.inventory-quantity').text()).toContain('73');
  });
  it('preserves the current snapshot while warming, then refreshes at two seconds', async () => {
    const warming = { success: false, http_status: 503, code: 'BOARD_WARMING', data: { availability: { state: 'warming', generated_at: null, age_seconds: 0, retry_after: 2 } } };
    fetchRealtimeBoard.mockResolvedValueOnce(payload()).mockResolvedValueOnce(warming).mockResolvedValueOnce(payload());
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    await vi.advanceTimersByTimeAsync(60000); await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    expect(wrapper.text()).not.toContain('正在准备当前查询范围的数据');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(2);
    expect(fetchRealtimeBoard.mock.calls[1][0].defer_inventory).toBe(1);
    await vi.advanceTimersByTimeAsync(1999); expect(fetchRealtimeBoard).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); await flushPromises();
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(3);
    expect(wrapper.text()).not.toContain('正在准备当前查询范围的数据');
    expect(wrapper.text()).toContain('1,000.00');
  });
  it('clears sales and inventory when warming reports a narrower scope version', async () => {
    const first = payload(); first.data.availability = { scope_version: 'scope-ab' };
    first.data.inventory_deferred = true;
    first.data.currency_groups[0].sku_ranking = [{ key: 'A', sku: 'A', name: '测试SKU', sales_amount: '1000', units_sold: 2 }];
    const warming = { success: true, data: { availability: { state: 'warming', scope_version: 'scope-a' } } };
    fetchRealtimeBoard.mockResolvedValueOnce(first)
      .mockResolvedValueOnce({ success: true, data: { inventory_only: true, inventory_by_currency: { PHP: { legacy: { sales_amount: { A: { available_qty: 73, status: 'available' } } } } }, stock_only_categories: {}, availability: { scope_version: 'scope-ab' } } })
      .mockResolvedValueOnce(warming);
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('73');
    await vi.advanceTimersByTimeAsync(60000); await flushPromises();
    expect(wrapper.text()).not.toContain('1,000.00');
    expect(wrapper.text()).not.toContain('73');
    expect(wrapper.text()).not.toContain('正在准备当前查询范围的数据');
  });
  it('clears a prior scope before showing a board-specific 503', async () => {
    const first = payload(); first.data.availability = { scope_version: 'scope-ab' };
    fetchRealtimeBoard.mockResolvedValueOnce(first).mockResolvedValueOnce({
      success: false, http_status: 503, message: '范围不可用', data: { availability: { scope_version: 'scope-a' } },
    });
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    await vi.advanceTimersByTimeAsync(60000); await flushPromises();
    expect(wrapper.text()).not.toContain('1,000.00');
    expect(wrapper.text()).toContain('范围不可用');
  });
  it('keeps the prior snapshot and loads inventory for a refreshing response', async () => {
    const refreshing = payload();
    refreshing.data.availability = { state: 'refreshing', generated_at: '2026-11-17T01:00:00Z', age_seconds: 30, retry_after: 60 };
    refreshing.data.inventory_deferred = true;
    fetchRealtimeBoard.mockResolvedValueOnce(payload()).mockResolvedValueOnce(refreshing)
      .mockResolvedValueOnce({ success: true, data: { inventory_only: true, inventory_by_currency: {} } });
    wrapper = mount(RealtimeBoard); await flushPromises();
    await vi.advanceTimersByTimeAsync(60000); await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    expect(wrapper.text()).not.toContain('数据正在更新');
    expect(wrapper.text()).not.toContain('当前显示快照');
    expect(fetchRealtimeBoard.mock.calls[2][0].inventory_only).toBe(1);
  });
  it('retries independently when the inventory snapshot is warming', async () => {
    const summary = payload(); summary.data.inventory_deferred = true;
    fetchRealtimeBoard.mockResolvedValueOnce(summary)
      .mockResolvedValueOnce({ success: true, data: { availability: { state: 'warming', valid_until: null } } })
      .mockResolvedValueOnce({ success: true, data: { inventory_only: true, inventory_by_currency: { PHP: {} }, stock_only_categories: {} } });
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(2);
    expect(fetchRealtimeBoard.mock.calls[1][0].inventory_only).toBe(1);
    await vi.advanceTimersByTimeAsync(1999); expect(fetchRealtimeBoard).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); await flushPromises();
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(3);
    expect(fetchRealtimeBoard.mock.calls[2][0].inventory_only).toBe(1);
  });
  it('clears inventory at valid_until and retries without showing expired stock', async () => {
    const summary = payload(); summary.data.inventory_deferred = true;
    summary.data.currency_groups[0].sku_ranking = [{ key: 'A', sku: 'A', name: '测试SKU', sales_amount: '1000', units_sold: 2 }];
    const valid_until = new Date(Date.now() + 10000).toISOString();
    fetchRealtimeBoard.mockResolvedValueOnce(summary)
      .mockResolvedValueOnce({ success: true, data: {
        inventory_only: true,
        inventory_by_currency: { PHP: { legacy: { sales_amount: { A: { available_qty: 73, status: 'available' } } } } },
        stock_only_categories: {}, availability: { valid_until },
      } })
      .mockResolvedValueOnce({ success: true, data: { availability: { state: 'warming', valid_until: null } } });
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('73');
    await vi.advanceTimersByTimeAsync(10000); await flushPromises();
    expect(wrapper.text()).not.toContain('73');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(3);
    expect(fetchRealtimeBoard.mock.calls[2][0].inventory_only).toBe(1);
  });
  it('shows warehouse categories when the selected dates have no sales', async () => {
    fetchRealtimeBoard.mockResolvedValueOnce({ success: true, data: { inventory_deferred: true, currency_groups: [] } })
      .mockResolvedValueOnce({ success: true, data: { inventory_only: true, stock_only_categories: {
        PHP: { sales_amount: [{ key: 'category:5', name: '仅有库存的分类', sales_amount: '0', units_sold: 0,
          inventory: { available_qty: 73, in_transit_qty: 4 } }] },
      } } });
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    expect(wrapper.text()).toContain('仅有库存的分类');
    expect(wrapper.find('.inventory-quantity').text()).toContain('73');
    expect(wrapper.find('.inventory-transit').text()).toContain('4');
  });
  it('keeps sales available and retries inventory after a failure', async () => {
    const summary = payload();
    summary.data.inventory_deferred = true;
    fetchRealtimeBoard.mockResolvedValueOnce(summary).mockRejectedValueOnce(new Error('timeout'))
      .mockResolvedValueOnce({ success: true, data: { inventory_only: true, inventory_by_currency: {} } });
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    const retry = wrapper.findAll('button').find(button => button.text() === '重试库存');
    expect(retry).toBeDefined();
    await retry.trigger('click');
    await flushPromises();
    expect(fetchRealtimeBoard.mock.calls[2][0]).toEqual(fetchRealtimeBoard.mock.calls[1][0]);
    expect(wrapper.text()).not.toContain('重试库存');
  });
  it('retries failed store filters independently of the board', async () => {
    fetchBoardFilters.mockResolvedValueOnce({ success: false });
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    expect(wrapper.text()).toContain('1,000.00');
    await wrapper.find('.board-notice button').trigger('click');
    await flushPromises();
    expect(fetchBoardFilters).toHaveBeenCalledTimes(2);
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).not.toContain('重试店铺筛选');
  });
  it('clears the previous result when access is denied', async () => {
    wrapper = mount(RealtimeBoard);
    await flushPromises();
    fetchRealtimeBoard.mockResolvedValue({ success: false, http_status: 403, message: '无权访问' });
    await vi.advanceTimersByTimeAsync(60000);
    expect(wrapper.text()).not.toContain('1,000.00');
    expect(wrapper.text()).toContain('无权访问');
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
    expect(wrapper.find('.product-panel .dimension-note').exists()).toBe(false);
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

  it('highlights advertising ROI and keeps missing transit inventory unknown in category rankings', async () => {
    const response = payload(), group = response.data.currency_groups[0];
    group.store_roi = '2.5'; group.ad_spend = '40';
    group.product_rankings = {
      category: { sales_amount: [{ key: 'cat', name: '床品', sales_amount: '100', units_sold: 4, inventory: { available_qty: null, in_transit_qty: null } }] }
    };
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.roi-ring').text()).toContain('2.50 倍');
    expect(wrapper.find('.ad-panel').text()).toContain('同范围费率');
    expect(wrapper.find('.board-grid').classes()).toContain('board-grid');
    const category = wrapper.findAll('.product-dimensions button').find(button => button.text() === '商品分类');
    await category.trigger('click');
    expect(wrapper.find('.product-table').text()).toContain('在途库存');
    expect(wrapper.find('.product-table').text()).toContain('未取得');
    expect(wrapper.find('.product-table').text()).not.toContain('在途库存0');
  });
  it('keeps unknown ROI guidance outside the ring and starts store and ad panels on the first grid row', async () => {
    const response = payload();
    Object.assign(response.data.currency_groups[0], { store_roi: null, ad_reason: 'ROI数据暂不可用' });
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.roi-ring strong').text()).toBe('—');
    expect(wrapper.find('.roi-ring').text()).not.toContain('ROI数据暂不可用');
    expect(wrapper.find('.roi-explanation').text()).toContain('ROI数据暂不可用');
    expect(wrapper.find('.store-panel').classes()).toContain('left-panel');
    expect(wrapper.find('.ad-panel').classes()).toContain('right-panel');
  });
  it('registers only a lazy menu entry, retaining action and internal-user gates', () => {
    const entry = menuItems.find(row => row.label === '销售管理').children.find(row => row.path === '/sales-management/realtime-board');
    expect(entry.label).toBe('实时数据大屏'); expect(entry.permissions).toEqual(['sales_management.view']);
    expect(canAccessPath({ user_type: 'external', permissions: ['sales_management.view'] }, entry.path)).toBe(false);
    expect(canAccessPath({ user_type: 'internal', permissions: [] }, entry.path)).toBe(false);
    expect(readFileSync('src/router/index.js', 'utf8')).toContain("const RealtimeBoard = () => import('../views/sales-management/RealtimeBoard.vue')");
  });
  it('switches the store ring metric and uses the whole-scope remainder', async () => {
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
    expect(wrapper.findAll('.donut-slice')).toHaveLength(2);
    await wrapper.findAll('.donut-slice')[1].trigger('mouseenter');
    expect(wrapper.find('.donut-center').text()).toContain('600.00');
    await wrapper.find('[aria-label="店铺排行指标"]').setValue('order_count');
    expect(wrapper.find('.store-ranking').text()).toContain('高订单店');
    expect(wrapper.find('.store-ranking').text()).toContain('20 单');
    await wrapper.find('.store-ranking li:first-child .store-detail button').trigger('click');
    expect(push.mock.lastCall[0].query.exclude_cancelled).toBeUndefined();
    expect(wrapper.find('.store-ranking').text()).not.toContain('其他店铺（其余范围）');
    expect(wrapper.find('.store-donut').attributes('aria-label')).toContain('当前范围');
    expect(wrapper.findAll('.donut-slice')).toHaveLength(0);
    await wrapper.find('[aria-label="商品排行指标"]').setValue('units_sold');
    expect(wrapper.find('.product-table').text()).toContain('高销量商品');
    expect(wrapper.find('.product-table').text()).not.toContain('高销售商品');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
  });
  it('suppresses the store ring when a negative contribution offsets positive sales', async () => {
    const response = payload(), group = response.data.currency_groups[0];
    group.sales_amount = '100';
    group.store_rankings = { sales_amount: [
      { store_id: 2, store_name: '正贡献', sales_amount: '120' },
      { store_id: 3, store_name: '净额调整', sales_amount: '-20' }
    ] };
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.find('.store-ranking').text()).toContain('正贡献');
    expect(wrapper.find('.store-ranking').text()).toContain('120.00');
    expect(wrapper.find('.store-ranking').text()).toContain('-20.00');
    expect(wrapper.findAll('.donut-slice')).toHaveLength(0);
    expect(wrapper.find('.store-panel .dimension-note').text()).toContain('范围包含净额调整');
  });
  it('shows all stores while grouping everything after the ninth into other', async () => {
    const response = payload(), group = response.data.currency_groups[0];
    group.sales_amount = '780';
    group.store_rankings = { sales_amount: Array.from({ length: 12 }, (_, index) => ({
      store_id: index + 1, store_name: `店铺${index + 1}`, sales_amount: String(120 - index * 10)
    })) };
    fetchRealtimeBoard.mockResolvedValue(response); wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.findAll('.store-ranking > li')).toHaveLength(12);
    expect(wrapper.find('.store-panel .panel-heading h2').text()).toBe('店铺占比与全量排行（12 家）');
    expect(wrapper.findAll('.donut-slice')).toHaveLength(10);
    expect(wrapper.find('.store-ranking > li:nth-child(10) .store-swatch').attributes('style')).toContain('#52647c');
    expect(wrapper.find('.store-ranking').text()).not.toContain('其他店铺（其余范围）');
    expect(wrapper.find('.store-panel .dimension-note').text()).toContain('TOP 9 店铺占当前范围：92.3%');
    await wrapper.find('.store-ranking > li:nth-child(12)').trigger('mouseenter');
    expect(wrapper.find('.donut-center').text()).toContain('其他店铺');
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


describe('国家范围和整店ROI', () => {
  it('filters authorized stores locally, submits region, and preserves it on drilldown', async () => {
    fetchBoardFilters.mockResolvedValueOnce({ success: true, data: { platforms: ['shopee'], stores: [
      { id: 2, name: '菲律宾店', region: 'PH', platform: 'shopee' },
      { id: 3, name: '马来店', region: 'MY', platform: 'shopee' }
    ] } });
    wrapper = mount(RealtimeBoard); await flushPromises();
    await wrapper.find('[aria-label="国家／站点"]').setValue('PH');
    const storeSelect = wrapper.find('.store-options');
    expect(storeSelect.text()).toContain('菲律宾店');
    expect(storeSelect.text()).not.toContain('马来店');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
    await wrapper.find('form').trigger('submit'); await flushPromises();
    expect(fetchRealtimeBoard.mock.calls.at(-1)[0].region).toBe('PH');
    await wrapper.find('.trend-footer button').trigger('click');
    expect(push).toHaveBeenLastCalledWith(expect.objectContaining({query: expect.objectContaining({region:'PH'})}));
  });
  it('applies multiple stores together and clears them on country changes', async () => {
    fetchBoardFilters.mockResolvedValueOnce({ success: true, data: { platforms: ['shopee'], stores: [
      { id: 2, name: '菲律宾店', region: 'PH', platform: 'shopee' },
      { id: 3, name: '马来店', region: 'MY', platform: 'shopee' }
    ] } });
    wrapper = mount(RealtimeBoard); await flushPromises();
    for (const input of wrapper.findAll('.store-options input')) await input.setValue(true);
    expect(wrapper.find('.store-filter summary').text()).toBe('已选 2 家店铺');
    expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
    await wrapper.find('form').trigger('submit'); await flushPromises();
    expect(fetchRealtimeBoard.mock.calls.at(-1)[0]).toMatchObject({ store_ids: '2,3', store_id: '' });
    await wrapper.find('[aria-label="国家／站点"]').setValue('PH');
    expect(wrapper.find('.store-filter summary').text()).toBe('全部授权店铺');
  });
  it('shows server-authorized ROI and country without calculating missing ROI locally', async () => {
    const response = payload(10);
    response.data.currency_groups[0].store_roi = '10.00';
    response.data.currency_groups[0].store_ranking[0].country_code = 'PH';
    fetchRealtimeBoard.mockResolvedValue(response);
    wrapper = mount(RealtimeBoard); await flushPromises();
    expect(wrapper.text()).toContain('10.00 倍');
    expect(wrapper.text()).toContain('菲律宾 · PH');
    response.data.currency_groups[0].store_roi = null;
    await wrapper.find('.header-actions button').trigger('click'); await flushPromises();
    expect(wrapper.text()).not.toContain('10.00 倍');
  });
});


it('loads decline module on demand and does not attach it to board polling', async () => {
  useAuthStore().currentUser.permissions.push('sales_management.skus.view');
  wrapper = mount(RealtimeBoard); await flushPromises();
  expect(fetchBoardDeclines).not.toHaveBeenCalled();
  const dates = wrapper.findAll('input[type="date"]');
  await dates[0].setValue('2025-01-02'); await dates[1].setValue('2025-01-02');
  await wrapper.find('form').trigger('submit'); await flushPromises();
  await wrapper.find('[aria-label="排行视图"]').findAll('button')[1].trigger('click');
  await vi.dynamicImportSettled(); await flushPromises();
  expect(fetchBoardDeclines).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(60000); await flushPromises();
  expect(fetchBoardDeclines).toHaveBeenCalledTimes(1);
});

it('restores returned board scope and metric, and blocks malformed return filters until manual apply', async () => {
  Object.assign(routeQuery, { view: 'declines', date_from: '2026-10-22', date_to: '2026-10-22', platform: 'lazada', region: 'MY', store_id: '7', currency: 'THB', metric: 'percent' });
  useAuthStore().currentUser.permissions.push('sales_management.skus.view');
  const restoredPayload = payload(); restoredPayload.data.currency_groups[0].currency = 'THB';
  fetchRealtimeBoard.mockResolvedValue(restoredPayload);
  wrapper = mount(RealtimeBoard); await flushPromises();
  expect(fetchRealtimeBoard.mock.calls[0][0]).toMatchObject({ date_from: '2026-10-22', date_to: '2026-10-22', platform: 'lazada', region: 'MY', store_id: '7' });
  await vi.dynamicImportSettled(); await flushPromises();
  expect(fetchBoardDeclines.mock.calls[0][0]).toMatchObject({ date_from: '2026-10-22', date_to: '2026-10-22', platform: 'lazada', region: 'MY', store_id: '7', currency: 'THB', metric: 'percent' });
  wrapper.unmount(); wrapper = null;
  Object.keys(routeQuery).forEach(key => delete routeQuery[key]); Object.assign(routeQuery, { view: 'declines', date_from: ['2026-10-22'], date_to: '2026-10-22' });
  fetchRealtimeBoard.mockClear(); fetchBoardDeclines.mockClear(); wrapper = mount(RealtimeBoard); await flushPromises();
  expect(fetchRealtimeBoard).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('返回的大屏筛选参数无效');
  const dates = wrapper.findAll('input[type="date"]'); await dates[0].setValue('2026-10-21'); await dates[1].setValue('2026-10-22'); await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
});

it('clears returned board scope and reloads the default board once without decline mode', async () => {
  Object.assign(routeQuery, { view: 'declines', date_from: '2026-10-22', date_to: '2026-10-22', platform: 'lazada', region: 'MY', store_id: '7', currency: 'THB', metric: 'percent' });
  useAuthStore().currentUser.permissions.push('sales_management.skus.view');
  fetchRealtimeBoard.mockResolvedValue(payload());
  wrapper = mount(RealtimeBoard); await flushPromises();
  expect(fetchRealtimeBoard).toHaveBeenCalledTimes(1);
  await vi.dynamicImportSettled(); await flushPromises();
  expect(fetchBoardDeclines).toHaveBeenCalledTimes(1);
  Object.keys(routeQuery).forEach(key => delete routeQuery[key]);
  await flushPromises();
  expect(fetchRealtimeBoard).toHaveBeenCalledTimes(2);
  const dates = wrapper.findAll('input[type="date"]');
  expect(fetchRealtimeBoard.mock.calls[1][0]).toMatchObject({ date_from: await dates[0].element.value, date_to: await dates[1].element.value, platform: '', region: '', store_id: '' });
  expect(wrapper.find('[aria-label="排行视图"]').findAll('button')[0].attributes('aria-pressed')).toBe('true');
  expect(fetchBoardDeclines).toHaveBeenCalledTimes(1);
});
