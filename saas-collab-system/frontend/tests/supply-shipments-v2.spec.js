import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ requestApi: vi.fn(), downloadApiFile: vi.fn(), canManage: false, routeQuery: {} }));
vi.mock('../src/api/request', () => mocks);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ authorizationStale: false, hasPermission: () => mocks.canManage }) }));
vi.mock('vue-router', async (original) => ({ ...(await original()), useRoute: () => ({ query: mocks.routeQuery }) }));
import * as api from '../src/api/supplyShipmentsV2';
import { ElMessageBox } from 'element-plus';
import { flushPromises, mount } from '@vue/test-utils';
import SupplyShipmentsV2 from '../src/views/purchasing/SupplyShipmentsV2.vue';

const order = { id: 7, number: 'PO-7', status: 'confirmed', lines: [{ id: 3, sku_id: 4, sku: 'SKU-4', product_name: 'Item', quantity: 2, unit_price: '3.25' }] };
const stubs = {
  AppPage: { template: '<main><slot name="action"/><slot/></main>' },
  'el-button': { props: ['disabled', 'loading', 'link'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p>{{title}}</p>' }, 'el-select': { template: '<div><slot/><slot name="footer"/></div>' },
  'el-option': { template: '<option><slot/></option>' }, 'el-pagination': { template: '<nav/>' },
  'el-table': { template: '<div><slot/></div>' }, 'el-table-column': { template: '<div><slot :row="{}" :$index="0"/></div>' },
  'router-link': { template: '<a><slot/></a>' },
  'el-drawer': { props: ['modelValue'], template: '<aside v-if="modelValue"><slot/><slot name="footer"/></aside>' },
  'el-input': { template: '<input/>' }, 'el-input-number': { template: '<input type="number"/>' }, 'el-date-picker': { template: '<input type="date"/>' },
  'el-form-item': { props: ['label'], template: '<label>{{label}}<slot/></label>' }, 'el-tag': { template: '<span><slot/></span>' }
};
function mountPage(supplier) { return mount(SupplyShipmentsV2, { props: { supplier }, global: { stubs, directives: { loading: () => {} } } }); }

describe('supplier shipment API', () => {
  beforeEach(() => { mocks.requestApi.mockReset().mockResolvedValue({ success: true, data: {} }); mocks.downloadApiFile.mockReset().mockResolvedValue({ success: true }); });

  it('uses the internal purchase and supplier-shipments routes with offset pagination', async () => {
    await api.fetchShipmentOrders(false, { limit: 20, offset: 40 });
    await api.fetchShipments(false, { limit: 20, offset: 40, order_id: 7 });
    await api.fetchShipment('a/b', false);
    expect(mocks.requestApi.mock.calls.map(([r]) => [r.method, r.url, r.params])).toEqual([
      ['get', '/api/internal/supply-chain/v2/purchase-orders/', { limit: 20, offset: 40, status: 'confirmed' }],
      ['get', '/api/internal/supply-chain/v2/supplier-shipments/', { limit: 20, offset: 40, order_id: 7 }],
      ['get', '/api/internal/supply-chain/v2/supplier-shipments/a%2Fb/', undefined]
    ]);
  });

  it('uses external shipment routes and limits supplier order selection to confirmed orders', async () => {
    await api.fetchShipmentOrders(true, { limit: 10, offset: 0 });
    await api.fetchShipments(true, { limit: 10, offset: 0 });
    await api.createShipment({ order_id: 7, lines: [] }, true, 'supplier-key');
    expect(mocks.requestApi.mock.calls.map(([r]) => [r.method, r.url, r.params])).toEqual([
      ['get', '/api/external/supplier/supply-chain/v2/purchase-orders/', { limit: 10, offset: 0, status: 'confirmed' }],
      ['get', '/api/external/supplier/supply-chain/v2/shipments/', { limit: 10, offset: 0 }],
      ['post', '/api/external/supplier/supply-chain/v2/shipments/', undefined]
    ]);
    expect(mocks.requestApi.mock.calls[2][0].headers['Idempotency-Key']).toBe('supplier-key');
  });

  it('keeps procurement-only price writes on the internal route', async () => {
    await api.updateShipmentPrices(9, { expected_version: 3, lines: [{ id: 2, unit_price: 4.5 }] }, 'price-key');
    expect(mocks.requestApi).toHaveBeenCalledWith(expect.objectContaining({
      method: 'patch', url: '/api/internal/supply-chain/v2/supplier-shipments/9/prices/',
      data: { expected_version: 3, lines: [{ id: 2, unit_price: 4.5 }] },
      headers: { 'Idempotency-Key': 'price-key' }
    }));
    expect(api.updateShipmentPrices).toBeTypeOf('function');
  });

  it('uses distinct external/internal list collection names and preserves saved line ids in updates', async () => {
    await api.fetchShipmentOptions(false);
    await api.fetchShipmentOptions(true);
    const data = { expected_version: 5, shipment_date: '2026-10-12', notes: '', lines: [{ id: 13, sku_id: 4, purchase_line_id: 8, quantity: 3 }] };
    await api.updateShipment(9, data, false, 'internal-key');
    await api.updateShipment(9, data, true, 'external-key');
    expect(mocks.requestApi.mock.calls.map(([r]) => r.url)).toEqual([
      '/api/internal/supply-chain/v2/shipment-options/',
      '/api/external/supplier/supply-chain/v2/shipment-options/',
      '/api/internal/supply-chain/v2/supplier-shipments/9/',
      '/api/external/supplier/supply-chain/v2/shipments/9/'
    ]);
    expect(mocks.requestApi.mock.calls[2][0].data.lines[0].id).toBe(13);
    expect(mocks.requestApi.mock.calls[3][0].data.lines[0]).not.toHaveProperty('unit_price');
  });

  it('mounts with valid table slots and allows supplier draft creation without exposing prices', async () => {
    mocks.canManage = false; mocks.routeQuery = { order_id: '7' };
    mocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/purchase-orders/7/')) return { success: true, data: order };
      if (request.url.endsWith('/purchase-orders/')) return { success: true, data: [order], count: 1 };
      if (request.url.endsWith('/shipment-options/')) return { success: true, data: { skus: [] } };
      if (request.method === 'post') return { success: true, data: { ...order, id: 19, order_id: 7, status: 'draft', version: 1, shipment_date: '2026-10-13', attachments: [] } };
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mountPage(true); await flushPromises();
    const create = wrapper.findAll('button').find(button => button.text().includes('新建发货草稿'));
    expect(create).toBeTruthy(); await create.trigger('click'); await flushPromises();
    expect(wrapper.text()).not.toContain('保存调价');
    expect(wrapper.text()).not.toContain('单价');
    expect(mocks.requestApi.mock.calls.some(([r]) => r.url.endsWith('/purchase-orders/7/'))).toBe(true);
    wrapper.unmount();
  });

  it('hides mutation controls for internal read-only users', async () => {
    mocks.canManage = false; mocks.routeQuery = {};
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/purchase-orders/') ? { success: true, data: [order], count: 1 } : request.url.endsWith('/shipment-options/') ? { success: true, data: { skus: [] } } : { success: true, data: [], count: 0 });
    const wrapper = mountPage(false); await flushPromises();
    expect(wrapper.text()).not.toContain('新建发货草稿');
    wrapper.unmount();
  });
  it('keeps procurement price and arrival controls out of a submitted supplier shipment', async () => {
    mocks.canManage=false; mocks.routeQuery={};
    const shipment={id:19,order_id:7,status:'submitted',editable:false,lines:[{id:2,sku_id:4,quantity:3}],attachments:[]};
    mocks.requestApi.mockImplementation(async request=>{
      if(request.url.endsWith('/purchase-orders/'))return {success:true,data:[order],count:1};
      if(request.url.endsWith('/shipment-options/'))return {success:true,data:{skus:[]}};
      if(request.url.endsWith('/shipments/19/'))return {success:true,data:shipment};
      return {success:true,data:[shipment],count:1};
    });
    const wrapper=mountPage(true);await flushPromises();
    await wrapper.findAll('button').find(button=>button.text()==='查看 / 编辑').trigger('click');await flushPromises();
    expect(wrapper.text()).not.toContain('保存调价');expect(wrapper.text()).not.toContain('标记到仓');
    expect(wrapper.findAll('button').some(button=>button.text()==='保存草稿')).toBe(false);wrapper.unmount();
  });

  it('preserves null procurement prices and reuses the idempotency key after a failed draft save', async () => {
    mocks.canManage = true; mocks.routeQuery = { order_id: '7' };
    const noPriceOrder = { ...order, lines: [{ ...order.lines[0], unit_price: null }] };
    let writes = 0;
    mocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/purchase-orders/')) return { success: true, data: [noPriceOrder], count: 1 };
      if (request.url.endsWith('/purchase-orders/7/')) return { success: true, data: noPriceOrder };
      if (request.url.endsWith('/shipment-options/')) return { success: true, data: { skus: [] } };
      if (request.method === 'post') { writes += 1; if (writes === 1) throw new Error('temporary network failure'); return { success: true, data: { id: 31, order_id: 7, order_number: 'PO-7', status: 'draft', version: 1, shipment_date: '2026-10-13', lines: request.data.lines, attachments: [] } }; }
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mountPage(false); await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('新建发货草稿')).trigger('click'); await flushPromises();
    const save = () => wrapper.findAll('button').find(button => button.text().includes('保存草稿')).trigger('click');
    await save(); await flushPromises(); await save(); await flushPromises();
    const postCalls = mocks.requestApi.mock.calls.map(([request]) => request).filter(request => request.method === 'post');
    expect(postCalls).toHaveLength(2);
    expect(postCalls[0].data.lines[0].unit_price).toBeNull();
    expect(postCalls[1].headers['Idempotency-Key']).toBe(postCalls[0].headers['Idempotency-Key']);
    wrapper.unmount();
  });

  it('displays inherited logistics dates and hides price writes after dispatch', async () => {
    mocks.canManage=true; mocks.routeQuery={};
    const shipment={id:19,order_id:7,status:'submitted',editable:false,price_editable:false,
      logistics_stage:'arrived_warehouse',logistics_dates:{departed_at:'2026-10-10T02:00:00Z',arrived_port_at:'2026-10-11T02:00:00Z',arrived_warehouse_at:'2026-10-12T02:00:00Z'},
      collection_arrived:true,lines:[{id:2,sku_id:4,quantity:3,unit_price:'12.5'}],attachments:[]};
    mocks.requestApi.mockImplementation(async r=>r.url.endsWith('/purchase-orders/')?{success:true,data:[order],count:1}:
      r.url.endsWith('/shipment-options/')?{success:true,data:{skus:[]}}:
      r.url.endsWith('/supplier-shipments/19/')?{success:true,data:shipment}:{success:true,data:[shipment],count:1});
    const wrapper=mount(SupplyShipmentsV2,{props:{supplier:false},global:{stubs:{...stubs,
      'el-table-column':{data:()=>({row:shipment}),template:'<div><slot :row="row" :$index="0"/></div>'}},directives:{loading:()=>{}}}});await flushPromises();
    await wrapper.findAll('button').find(b=>b.text()==='查看 / 编辑').trigger('click');await flushPromises();
    expect(wrapper.text()).toContain('批次物流状态');
    expect(wrapper.text()).toContain('目的仓到仓时间');
    expect(wrapper.text()).toContain('2026');
    expect(wrapper.text()).not.toContain('保存调价');
    expect(wrapper.findAll('input[type="number"]').length).toBe(0);
    wrapper.unmount();
  });

  it('requires and submits a reason for a post-collection price adjustment', async () => {
    mocks.canManage=true; mocks.routeQuery={};
    const wrapper=mountPage(false);
    wrapper.vm.current={id:31,status:'submitted',version:4,price_editable:true,price_adjustment_requires_reason:true};
    wrapper.vm.form.lines=[{id:8,unit_price:0}];
    await wrapper.vm.savePrices();
    expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/prices/'))).toBe(false);
    wrapper.vm.priceReason='集货后供应商更新报价';
    mocks.requestApi.mockImplementation(async r=>r.url.endsWith('/prices/')?{success:true,data:{id:31,status:'submitted',version:5,lines:[]}}:{success:true,data:[]});
    await wrapper.vm.savePrices();
    const request=mocks.requestApi.mock.calls.map(([r])=>r).find(r=>r.url.endsWith('/prices/'));
    expect(request.data.reason).toBe('集货后供应商更新报价');
    wrapper.unmount();
  });

  it.each([{ supplier: false }, { supplier: true }])('saves factory-loading mode and address for supplier=$supplier without exposing supplier prices', async ({ supplier }) => {
    mocks.canManage = true; mocks.routeQuery = { order_id: '7' };
    mocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/purchase-orders/')) return { success: true, data: [order], count: 1 };
      if (request.url.endsWith('/purchase-orders/7/')) return { success: true, data: order };
      if (request.url.endsWith('/shipment-options/')) return { success: true, data: { skus: [] } };
      if (request.method === 'post') return { success: true, data: { id: 41, order_id: 7, order_number: 'PO-7', status: 'draft', version: 1, shipment_date: request.data.shipment_date, delivery_mode: request.data.delivery_mode, loading_address: request.data.loading_address, notes: request.data.notes, lines: request.data.lines, attachments: [] } };
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mountPage(supplier); await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('新建发货草稿')).trigger('click'); await flushPromises();
    wrapper.vm.form.delivery_mode = 'factory_loading';
    wrapper.vm.form.loading_address = '深圳市宝安区工厂 8 号门';
    await flushPromises();
    expect(wrapper.text()).toContain('装柜地址（提交时必填）');
    if (supplier) expect(wrapper.text()).not.toContain('单价');
    await wrapper.findAll('button').find(button => button.text().includes('保存草稿')).trigger('click'); await flushPromises();
    const saveRequest = mocks.requestApi.mock.calls.map(([request]) => request).find(request => request.method === 'post');
    expect(saveRequest.data.delivery_mode).toBe('factory_loading');
    expect(saveRequest.data.loading_address).toBe('深圳市宝安区工厂 8 号门');
    if (supplier) expect(saveRequest.data.lines[0]).not.toHaveProperty('unit_price');
    wrapper.unmount();
  });

  it('allows a blank-address draft save, then blocks factory-loading submission with a clear prompt', async () => {
    mocks.canManage = true; mocks.routeQuery = { order_id: '7' };
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(true);
    mocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/purchase-orders/')) return { success: true, data: [order], count: 1 };
      if (request.url.endsWith('/purchase-orders/7/')) return { success: true, data: order };
      if (request.url.endsWith('/shipment-options/')) return { success: true, data: { skus: [] } };
      if (request.method === 'post') return { success: true, data: { id: 42, order_id: 7, order_number: 'PO-7', status: 'draft', version: 1, shipment_date: request.data.shipment_date, delivery_mode: request.data.delivery_mode, loading_address: '', lines: request.data.lines, attachments: [{ id: 1, file_name: 'boxes.pdf' }] } };
      if (request.url.endsWith('/submit/')) return { success: true, data: { id: 42, status: 'submitted' } };
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mountPage(false); await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('新建发货草稿')).trigger('click'); await flushPromises();
    wrapper.vm.form.delivery_mode = 'factory_loading';
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('保存草稿')).trigger('click'); await flushPromises();
    expect(mocks.requestApi.mock.calls.some(([request]) => request.method === 'post')).toBe(true);
    const submit = wrapper.findAll('button').find(button => button.text().includes('提交发货'));
    expect(submit).toBeTruthy();
    await submit.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('货柜上门装载的发货单提交前必须填写装柜地址。');
    expect(mocks.requestApi.mock.calls.some(([request]) => request.url.endsWith('/submit/'))).toBe(false);
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore(); wrapper.unmount();
  });

  it('uses the address returned by draft save before allowing factory-loading submission', async () => {
    mocks.canManage = true; mocks.routeQuery = { order_id: '7' };
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(true);
    mocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/purchase-orders/')) return { success: true, data: [order], count: 1 };
      if (request.url.endsWith('/purchase-orders/7/')) return { success: true, data: order };
      if (request.url.endsWith('/shipment-options/')) return { success: true, data: { skus: [] } };
      if (request.method === 'post') return { success: true, data: { id: 43, order_id: 7, order_number: 'PO-7', status: 'draft', version: 1, shipment_date: request.data.shipment_date, delivery_mode: request.data.delivery_mode, loading_address: '供应商默认装柜地址', lines: request.data.lines, attachments: [{ id: 1, file_name: 'boxes.pdf' }] } };
      if (request.url.endsWith('/submit/')) return { success: true, data: { id: 43, order_id: 7, status: 'submitted', version: 2, delivery_mode: 'factory_loading', loading_address: '供应商默认装柜地址', lines: order.lines, attachments: [{ id: 1, file_name: 'boxes.pdf' }] } };
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mountPage(false); await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('新建发货草稿')).trigger('click'); await flushPromises();
    wrapper.vm.form.delivery_mode = 'factory_loading';
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('保存草稿')).trigger('click'); await flushPromises();
    expect(wrapper.vm.form.loading_address).toBe('供应商默认装柜地址');
    await wrapper.findAll('button').find(button => button.text().includes('提交发货')).trigger('click'); await flushPromises();
    expect(mocks.requestApi.mock.calls.some(([request]) => request.url.endsWith('/submit/'))).toBe(true);
    confirm.mockRestore(); wrapper.unmount();
  });

  it('saves collection-center mode without an unnecessary loading address', async () => {
    mocks.canManage = true; mocks.routeQuery = { order_id: '7' };
    mocks.requestApi.mockImplementation(async request => {
      if (request.url.endsWith('/purchase-orders/')) return { success: true, data: [order], count: 1 };
      if (request.url.endsWith('/purchase-orders/7/')) return { success: true, data: order };
      if (request.url.endsWith('/shipment-options/')) return { success: true, data: { skus: [] } };
      if (request.method === 'post') return { success: true, data: { id: 44, order_id: 7, order_number: 'PO-7', status: 'draft', version: 1, shipment_date: request.data.shipment_date, delivery_mode: request.data.delivery_mode, lines: request.data.lines, attachments: [] } };
      return { success: true, data: [], count: 0 };
    });
    const wrapper = mountPage(false); await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('新建发货草稿')).trigger('click'); await flushPromises();
    await wrapper.findAll('button').find(button => button.text().includes('保存草稿')).trigger('click'); await flushPromises();
    const saveRequest = mocks.requestApi.mock.calls.map(([request]) => request).find(request => request.method === 'post');
    expect(saveRequest.data.delivery_mode).toBe('collection_center');
    expect(saveRequest.data).not.toHaveProperty('loading_address');
    wrapper.unmount();
  });

  it('hides arrival marking for submitted factory loading and retains it for collection-center shipments', async () => {
    mocks.canManage = true; mocks.routeQuery = {};
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/purchase-orders/') ? { success: true, data: [order], count: 1 } : request.url.endsWith('/shipment-options/') ? { success: true, data: { skus: [] } } : { success: true, data: [], count: 0 });
    const wrapper = mountPage(false); await flushPromises();
    wrapper.vm.current = { id: 51, order_id: 7, status: 'submitted', delivery_mode: 'factory_loading', attachments: [] };
    wrapper.vm.open = true;
    await flushPromises();
    expect(wrapper.text()).not.toContain('标记到仓');
    wrapper.vm.current = { id: 52, order_id: 7, status: 'submitted', delivery_mode: 'collection_center', attachments: [] };
    await flushPromises();
    expect(wrapper.text()).toContain('标记到仓');
    wrapper.unmount();
  });
});
