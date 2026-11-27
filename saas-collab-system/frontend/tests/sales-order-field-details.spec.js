import { mount, flushPromises } from '@vue/test-utils';
import { computed } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchSalesPage: vi.fn(), fetchSalesFilters: vi.fn(), fetchSalesOrderDetail: vi.fn(), createSalesExport: vi.fn() }));
vi.mock('../src/api/salesManagement', () => api);
vi.mock('../src/api/feishuReminders', () => ({ reminderOptions: vi.fn().mockResolvedValue({ data: {} }) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ query: {} }) }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: { permissions: [] }, hasPermission: () => false }) }));
import SalesWorkspace from '../src/views/sales-management/SalesWorkspace.vue';
import SalesOrderDetailPanel from '../src/components/SalesOrderDetailPanel.vue';
import OrderWarehouseInfo from '../src/components/OrderWarehouseInfo.vue';

let wrapper;
const stubs = {
  ElForm: { template: '<form><slot /></form>' }, ElFormItem: { template: '<label><slot /></label>' },
  ElButton: { template: '<button><slot /></button>' }, ElSelect: true, ElOption: true,
  ElDatePicker: true, ElInput: true, ElPagination: true, ElDialog: { props: ['modelValue'], template: '<aside v-if="modelValue"><slot /></aside>' },
  ElAlert: { props: ['title'], template: '<p>{{ title }}</p>' }, ElTag: { template: '<span><slot /></span>' },
  ElTable: { props: ['data'], provide() { return { rows: computed(() => this.data) }; }, template: '<div><slot /></div>' },
  ElTableColumn: { props: ['label'], inject: ['rows'], template: '<section>{{ label }}<slot v-for="row in rows" :row="row" /></section>' },
  ElEmpty: true, ElDrawer: { props: ['modelValue'], template: '<aside v-if="modelValue"><slot /></aside>' },
};
beforeEach(() => {
  vi.clearAllMocks();
  api.fetchSalesFilters.mockResolvedValue({ success: true, data: {} });
  api.fetchSalesPage.mockResolvedValue({ success: true, data: { results: [] } });
});
afterEach(() => { wrapper?.unmount(); vi.unstubAllEnvs(); });

it('propagates warehouse completion to detail and list without reloading orders', async () => {
  vi.stubEnv('VITE_USE_MOCK', 'false');
  api.fetchSalesPage.mockResolvedValue({ success: true, data: { results: [{ id: 1, external_order_id: 'ORDER-1' }] } });
  await openDetail({ id: 1, external_order_id: 'ORDER-1' });
  const summary = { status: 'matched', snapshot: { warehouse_name: 'WAREHOUSE-RESULT', packages: [] } };
  wrapper.findComponent(OrderWarehouseInfo).vm.$emit('updated', { orderId: 1, summary });
  await flushPromises();
  expect(wrapper.findComponent(SalesOrderDetailPanel).props('order').warehouse_summary).toEqual(summary);
  expect(wrapper.vm.rows[0].warehouse_summary).toEqual(summary);
  wrapper.findComponent(OrderWarehouseInfo).vm.$emit('updated', { orderId: 99, summary: { status: 'failed' } });
  await flushPromises();
  expect(wrapper.vm.rows[0].warehouse_summary.status).toBe('matched');
});
async function openDetail(data) {
  api.fetchSalesOrderDetail.mockResolvedValue({ success: true, data });
  wrapper = mount(SalesWorkspace, { props: { mode: 'orders' }, global: { stubs, directives: { loading: () => {} } } });
  await flushPromises(); await wrapper.vm.selectRow({ id: 1 }); await flushPromises();
}

describe('sales order field details', () => {
  it.each(['mock', 'degraded'])('rejects %s detail data in production mode and permits a real retry', async (api_status) => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    await openDetail({ id: 1, api_status, external_order_id: 'FAKE-DETAIL', order_total_amount: '999999',
      items: [{ id: 1, seller_sku: 'FAKE-PRODUCT', quantity: 1 }] });
    expect(wrapper.text()).not.toContain('FAKE-DETAIL');
    expect(wrapper.text()).not.toContain('FAKE-PRODUCT');
    expect(wrapper.text()).not.toContain('999,999');
    expect(wrapper.text()).toContain('不能使用示例数据');
    api.fetchSalesOrderDetail.mockResolvedValue({ success: true, data: { id: 1, external_order_id: 'REAL-DETAIL' } });
    await wrapper.vm.selectRow({ id: 1 }); await flushPromises();
    expect(wrapper.text()).toContain('REAL-DETAIL');
    expect(wrapper.text()).not.toContain('不能使用示例数据');
  });
  it('ignores an older degraded response after switching orders', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');
    await openDetail({ id: 1, external_order_id: 'FIRST' });
    let resolveOld;
    api.fetchSalesOrderDetail.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ success: true, data: { id: 3, external_order_id: 'LATEST' } });
    const pending = wrapper.vm.selectRow({ id: 2 });
    await wrapper.vm.selectRow({ id: 3 });
    resolveOld({ success: true, data: { api_status: 'degraded', external_order_id: 'FAKE-OLD' } });
    await pending; await flushPromises();
    expect(wrapper.text()).toContain('LATEST');
    expect(wrapper.text()).not.toContain('FAKE-OLD');
    expect(wrapper.text()).not.toContain('不能使用示例数据');
  });
  it('separates refund status amounts and flags an unreconciled item instead of showing zero', async () => {
    await openDetail({ id: 1, platform: 'shopee', currency: 'PHP', refund_summary: {
      case_count: 3, refund_amount: '20', accepted_amount: '30', cancelled_amount: '40' },
      refund_returns: [{ id: 1, normalized_status: 'accepted', currency: 'PHP', refund_amount: '999',
        items: [{ quantity: 2, currency: 'PHP', refund_amount: null, amount_observations: {
          refund_amount_basis: 'unverified', reported_refund_amount: '524' } }] }] });
    expect(wrapper.text()).toContain('已完成退款金额');
    expect(wrapper.text()).toContain('已接受售后金额');
    expect(wrapper.text()).toContain('已取消售后金额');
    expect(wrapper.text()).toContain('待核对');
    expect(wrapper.text()).toContain('原值 524 PHP');
    expect(wrapper.text()).toContain('不计入商品退款金额汇总');
  });
  it('shows an order-linked return snapshot without inventing a local aftersales record', async () => {
    await openDetail({ id: 1, platform: 'shopee', refund_returns: [], order_observations: {
      return_logistics_snapshots: [{ return_sn: 'SYNTHETIC-RETURN', status: 'ok',
        buyer_return: { tracking_number: 'RETURN-WITHOUT-LOCAL-CASE' } }] } });
    expect(wrapper.text()).toContain('SYNTHETIC-RETURN');
    expect(wrapper.text()).toContain('RETURN-WITHOUT-LOCAL-CASE');
    expect(wrapper.text()).toContain('未创建售后登记');
    expect(api.fetchSalesOrderDetail).toHaveBeenCalledTimes(1);
  });
  it('shows separately collected forward and reverse logistics without automatic network queries', async () => {
    await openDetail({ id: 1, platform: 'shopee', order_observations: { platform_logistics: {
      status: 'ok', collected_at_utc: '2026-09-01T00:00:00Z', packages: [{ package_number: 'SYNTHETIC-PACKAGE',
        tracking_number: 'FORWARD-TRACK', events: [{ occurred_at_utc: '2026-09-01T01:00:00Z', description: 'Synthetic outbound' }] }] } },
      refund_returns: [{ id: 1, platform_logistics: { status: 'ok', buyer_return: { tracking_number: 'BUYER-TRACK' }, post_return: { tracking_number: 'POST-TRACK' } } }] });
    expect(wrapper.text()).toContain('FORWARD-TRACK');
    expect(wrapper.text()).toContain('BUYER-TRACK');
    expect(wrapper.text()).toContain('POST-TRACK');
    expect(wrapper.text()).toContain('Synthetic outbound');
    expect(wrapper.text()).toContain('不代表本地仓库已出库或入仓');
    expect(api.fetchSalesOrderDetail).toHaveBeenCalledTimes(1);
  });
  it('separates Shopee booking, pickup, deadline and warehouse evidence', async () => {
    await openDetail({ id: 1, platform: 'shopee', external_order_id: 'SYNTHETIC-ORDER',
      order_observations: { booking_sn: 'AAS-SYNTHETIC', platform_pickup_at_utc: '2026-09-01T01:00:00Z',
        ship_by_at_utc: '2026-09-02T01:00:00Z', actual_shipping_fee_confirmed: false,
        fulfillment_flag: 'fulfilled_by_cb_seller' },
      refund_returns: [{ id: 1, case_type: 'refund_only', normalized_status: 'accepted', requires_physical_return: false }] });
    expect(wrapper.text()).toContain('AAS-SYNTHETIC');
    expect(wrapper.text()).toContain('平台揽收时间（UTC）');
    expect(wrapper.text()).toContain('2026-09-01 01:00:00');
    expect(wrapper.text()).toContain('2026-09-02 01:00:00');
    expect(wrapper.text()).toContain('不替代仓库实际出库');
    expect(wrapper.text()).toContain('不等于退款已支付');
    const rows = wrapper.findAll('.detail-list > div');
    expect(rows.find(row => row.find('dt').text() === '实际运费已确认').find('dd').text()).toBe('否');
    expect(api.fetchSalesOrderDetail).toHaveBeenCalledTimes(1);
  });
  it('shows explicit observations and masked recipient summary without another collection request', async () => {
    await openDetail({ id: 1, external_order_id: 'SYNTHETIC-ORDER', updated_at_utc: '2026-09-01T00:00:00Z',
      order_observations: { payment_method: 'Synthetic payment', shipping_carrier: 'Synthetic carrier',
        recipient_summary: { name_masked: 'S***', phone_masked: '***7890', city: 'Test city' } },
      items: [{ seller_sku: 'SYNTHETIC-SKU', variation_snapshot: 'Test variation', quantity: 1 }] });
    expect(wrapper.text()).toContain('Synthetic payment'); expect(wrapper.text()).toContain('Synthetic carrier');
    expect(wrapper.text()).toContain('***7890'); expect(wrapper.text()).toContain('Test city');
    expect(wrapper.text()).toContain('平台规格 ID'); expect(wrapper.text()).toContain('商品行税额');
    expect(api.fetchSalesOrderDetail).toHaveBeenCalledTimes(1);
    expect(api.fetchSalesPage).toHaveBeenCalledTimes(1);
  });
  it('keeps absent charges distinct from explicit zero and explains missing logistics', async () => {
    await openDetail({ id: 1, seller_discount_amount: null, platform_discount_amount: '0.0000', order_observations: {} });
    const details = wrapper.findAll('.detail-list > div');
    expect(details.find(row => row.find('dt').text() === '商家优惠').find('dd').text()).toBe('—');
    expect(details.find(row => row.find('dt').text() === '平台优惠').find('dd').text()).toBe('0.00');
    expect(wrapper.text()).toContain('不据此判定未发货');
  });
});
