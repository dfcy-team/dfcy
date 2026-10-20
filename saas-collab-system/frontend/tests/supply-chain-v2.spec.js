import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  requestApi: vi.fn(), downloadApiFile: vi.fn(), error: vi.fn(), success: vi.fn(), confirm: vi.fn(),
  permissions: new Set(), routeView: false,
}));
vi.mock('../src/api/request', () => ({ requestApi: mocks.requestApi, downloadApiFile: mocks.downloadApiFile }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: code => mocks.permissions.has(code), currentUser: null, authorizationStale: false }) }));
vi.mock('../src/router/menu', () => ({ canAccessPath: () => mocks.routeView }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessage: { error: mocks.error, success: mocks.success }, ElMessageBox: { confirm: mocks.confirm } }));

import SupplyProcurementV2 from '../src/views/purchasing/SupplyProcurementV2.vue';
import FulfillmentProgressV2 from '../src/components/supply-chain/FulfillmentProgressV2.vue';
import * as api from '../src/api/supplyChainV2';

const BASE = '/api/internal/supply-chain/v2/';
const ok = (data, extras = {}) => ({ success: true, code: 'OK', message: 'success', data, ...extras });
const order = (changes = {}) => ({ id: 8, number: 'PO-20261012-A', supplier_id: 2, supplier_name: '供应商甲', country_id: 3, country_name: '泰国', country_code: 'TH', source_kind: 'manual', status: 'draft', version: 4, order_date: '2026-10-01', reference_number: 'REF', notes: '', prices_complete: true, total_quantity: 2, total_amount: '8.00', lines: [{ id: 1, sku_id: 6, sku: 'SKU-A', name: '商品甲', quantity: 2, unit_price: '4.00', product_reference_price: '5.00', supplier_reference_price: '4.00', import_row_number: null }], ...changes });
const pass = { template: '<div><slot /></div>' };
const stubs = {
  'router-link': { template: '<a><slot /></a>' },
  AppPage: { props: ['title', 'subtitle'], template: '<main><h1>{{ title }}</h1><p>{{ subtitle }}</p><slot name="action" /><slot /></main>' },
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>' },
  'el-alert': { props: ['title'], template: '<p role="alert">{{ title }}</p>' },
  'el-input': { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-input-number': { props: ['modelValue', 'disabled'], template: '<input type="number" :value="modelValue" :disabled="disabled" />' },
  'el-select': { props: ['modelValue', 'disabled'], template: '<div><select :disabled="disabled"><slot /></select><slot name="footer" /></div>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-tabs': pass, 'el-tab-pane': { props: ['label'], template: '<span>{{ label }}</span>' },
  'el-table': { props: ['data', 'emptyText'], template: '<section><span>{{ emptyText }}</span><slot /></section>' },
  'el-table-column': { template: '<div><slot :row="{}" :$index="0" /></div>' },
  'el-drawer': { props: ['modelValue', 'title'], template: '<aside v-if="modelValue"><h2>{{ title }}</h2><slot /><slot name="footer" /></aside>' },
  'el-dialog': { props: ['modelValue', 'title'], template: '<article v-if="modelValue"><h2>{{ title }}</h2><slot /><slot name="footer" /></article>' },
  'el-form': pass, 'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-tag': pass, 'el-date-picker': { props: ['disabled'], template: '<input :disabled="disabled" />' }, 'el-switch': { template: '<input type="checkbox" />' }, 'el-pagination': { template: '<nav />' },
};
const createPage = () => mount(SupplyProcurementV2, { global: { stubs, directives: { loading: () => {} } } });
const writes = () => mocks.requestApi.mock.calls.map(([request]) => request).filter(request => request.method !== 'get');
function validDraft(vm, price = null) { Object.assign(vm.orderForm, { supplier_id: 2, country_id: 3, reference_number: '重复参考号', order_date: '2026-10-01', notes: '', lines: [{ sku_id: 6, sku: 'SKU-A', name: '商品甲', quantity: 2, unit_price: price, price_defaulted: false }] }); }

beforeEach(() => {
  vi.clearAllMocks(); mocks.permissions = new Set(['supply.v2.view', 'supply.v2.manage']); mocks.routeView = false;
  mocks.confirm.mockResolvedValue('confirm'); mocks.downloadApiFile.mockResolvedValue(ok(null));
  mocks.requestApi.mockImplementation(async request => {
    if (request.url.endsWith('/options/')) return ok([], { count: 0 });
    if (request.method === 'get' && request.url === `${BASE}purchase-orders/8/`) return ok(order());
    if (request.method === 'get') return ok([order()], { count: 120 });
    return ok(order());
  });
});

describe('purchase duplicate line validation',()=>{
  it('blocks repeated SKUs and reports every affected row without an API write',async()=>{
    const wrapper=createPage();
    await flushPromises();
    wrapper.vm.openCreate();
    validDraft(wrapper.vm);
    wrapper.vm.orderForm.lines.push({...wrapper.vm.orderForm.lines[0]});
    wrapper.vm.orderForm.lines.push({...wrapper.vm.orderForm.lines[0]});
    mocks.requestApi.mockClear();
    await wrapper.vm.saveOrder();
    expect(writes()).toHaveLength(0);
    expect(wrapper.text()).toContain('重复行号：1、2、3');
    wrapper.unmount();
  });
});

describe('supply-chain v2 API boundary', () => {
  it('uses real versioned PATCH writes, mandatory action keys, and authenticated file downloads', async () => {
    const data = { expected_version: 4 };
    await api.updatePurchaseOrder(8, data, 'draft-key'); await api.updateSupplier(2, data, 'supplier-key'); await api.updateFreightCompany(3, data, 'freight-key');
    expect(writes().map(request => [request.method, request.url, request.headers['Idempotency-Key']])).toEqual([
      ['patch', `${BASE}purchase-orders/8/`, 'draft-key'], ['patch', `${BASE}suppliers/2/`, 'supplier-key'], ['patch', `${BASE}freight-companies/3/`, 'freight-key'],
    ]);
    await api.downloadImportTemplate(); await api.downloadPurchaseExcel(8, 'PO-A'); await api.downloadPurchaseLabels(8, 'PO-A');
    expect(mocks.downloadApiFile.mock.calls).toEqual([[`${BASE}imports/template/`, 'supply-chain-import-template.xlsx'], [`${BASE}purchase-orders/8/excel/`, 'PO-A.xlsx'], [`${BASE}purchase-orders/8/labels/`, 'PO-A-labels.pdf']]);
  });

  it('posts a multipart workbook with its idempotency key and waits for import processing', async () => {
    const file = new File(['workbook'], 'purchase.xlsx'); await api.previewImport(file, 'import-key');
    const request = writes()[0];
    expect(request.url).toBe(`${BASE}imports/`); expect(request.data.get('file')).toBe(file);
    expect(request.headers['Idempotency-Key']).toBe('import-key'); expect(request.timeout).toBe(60000);
  });
});

describe('procurement permissions and server paging', () => {
  it('opens relocated archives without procurement actions and reloads when archive routes switch', async () => {
    const wrapper = mount(SupplyProcurementV2, { props: { archiveKind: 'prices' }, global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    expect(wrapper.find('h1').text()).toBe('供应商价格');
    expect(wrapper.text()).not.toContain('新建采购单');
    expect(wrapper.text()).not.toContain('Excel 导入');
    expect(mocks.requestApi.mock.calls.some(([r]) => r.url === `${BASE}supplier-prices/`)).toBe(true);
    expect(mocks.requestApi.mock.calls.some(([r]) => r.url === `${BASE}purchase-orders/`)).toBe(false);
    await wrapper.setProps({ archiveKind: 'freight' }); await flushPromises();
    expect(wrapper.find('h1').text()).toBe('货运公司');
    expect(mocks.requestApi).toHaveBeenLastCalledWith(expect.objectContaining({ url: `${BASE}freight-companies/` }));
    wrapper.unmount();
  });
  it('does not read or write procurement data without view permission', async () => {
    mocks.permissions.clear(); const wrapper = createPage(); await flushPromises();
    expect(wrapper.text()).toContain('没有采购协同查看权限'); expect(mocks.requestApi).not.toHaveBeenCalled();
    wrapper.vm.openCreate(); await wrapper.vm.saveOrder(); await wrapper.vm.commitImportFile();
    expect(writes()).toHaveLength(0); wrapper.unmount();
  });

  it('lets a menu-implied viewer read while keeping all mutations unavailable', async () => {
    mocks.permissions.clear(); mocks.routeView = true; const wrapper = createPage(); await flushPromises();
    expect(wrapper.text()).toContain('当前为只读模式'); expect(wrapper.text()).not.toContain('新建采购单'); expect(wrapper.findAll('button').some(button => button.text() === 'Excel 导入')).toBe(false);
    await wrapper.vm.openDetail({ id: 8 }); validDraft(wrapper.vm, 4); await wrapper.vm.saveOrder(); await wrapper.vm.actOnOrder('confirm'); await wrapper.vm.actOnOrder('cancel');
    wrapper.vm.activeTab = 'suppliers'; wrapper.vm.openArchive(); await wrapper.vm.saveArchive(); wrapper.vm.openImport();
    expect(writes()).toHaveLength(0); expect(mocks.confirm).not.toHaveBeenCalled(); expect(wrapper.vm.archiveOpen).toBe(false); wrapper.unmount();
  });

  it('queries the server for filters and later pages, including archive and price history pages', async () => {
    const wrapper = createPage(); await flushPromises();
    Object.assign(wrapper.vm.filters, { search: ' REF ', status: 'draft', source_kind: 'import' }); await wrapper.vm.applyFilters(); await wrapper.vm.changePage(3);
    expect(mocks.requestApi).toHaveBeenLastCalledWith(expect.objectContaining({ url: `${BASE}purchase-orders/`, params: { search: 'REF', status: 'draft', source_kind: 'import', limit: 10, offset: 20, include_workflow_counts:'1' } }));
    wrapper.vm.activeTab = 'prices'; wrapper.vm.filters.supplier_id = 2; await wrapper.vm.applyFilters();
    expect(mocks.requestApi).toHaveBeenLastCalledWith(expect.objectContaining({ url: `${BASE}supplier-prices/`, params: expect.objectContaining({ supplier_id: 2 }) }));
    await wrapper.vm.openHistory({ id: 9, supplier_name: '甲', sku: 'SKU-A' }); await wrapper.vm.changeHistoryPage(3);
    expect(mocks.requestApi).toHaveBeenLastCalledWith({ method: 'get', url: `${BASE}supplier-prices/9/history/`, params: { limit: 20, offset: 40 } }); wrapper.unmount();
  });

  it('keeps the operating tab connected after saving and cancelling a purchase opened from a split', async () => {
    const wrapper = createPage(); await flushPromises();
    wrapper.vm.activeTab = 'operating'; await wrapper.vm.changeTab(); await flushPromises();
    await wrapper.vm.openDetail({ id: 8 }); validDraft(wrapper.vm, 3.5);
    await wrapper.vm.saveOrder(); await flushPromises();
    expect(wrapper.find('main').attributes('capability')).toBe('connected');
    await wrapper.vm.actOnOrder('cancel'); await flushPromises();
    expect(wrapper.find('main').attributes('capability')).toBe('connected');
    expect(writes().some(request => request.url === `${BASE}purchase-orders/8/cancel/`)).toBe(true);
    wrapper.unmount();
  });

  it('loads more remote options beyond the first page instead of capping the available SKUs', async () => {
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/options/') ? ok([{ id: request.params.offset + 1, sku: `SKU-${request.params.offset}`, name: '商品' }], { count: 121 }) : ok([], { count: 0 }));
    const wrapper = createPage(); await flushPromises(); await wrapper.vm.searchSkus('SKU'); await wrapper.vm.loadMoreOptions('skus');
    const calls = mocks.requestApi.mock.calls.map(([request]) => request).filter(request => request.url.endsWith('/options/'));
    expect(calls[1].params).toMatchObject({ kind: 'skus', search: 'SKU', offset: 1, limit: 50 }); expect(wrapper.vm.hasMoreOptions('skus')).toBe(true); expect(wrapper.vm.options.skus.rows).toHaveLength(2); wrapper.unmount();
  });
});

describe('procurement draft forms and transitions', () => {
  it('validates quantities, allows a missing price draft and blocks confirming that draft', async () => {
    mocks.requestApi.mockImplementation(async request => request.method === 'get' ? ok([], { count: 0 }) : ok(order({ prices_complete: false, total_amount: null, lines: [{ sku_id: 6, sku: 'SKU-A', quantity: 2, unit_price: null }] })));
    const wrapper = createPage(); await flushPromises(); wrapper.vm.openCreate(); validDraft(wrapper.vm); wrapper.vm.orderForm.lines.push({ ...wrapper.vm.orderForm.lines[0] });
    await wrapper.vm.saveOrder(); expect(wrapper.vm.formError).toContain('1、2'); expect(writes()).toHaveLength(0);
    wrapper.vm.orderForm.lines.splice(1); wrapper.vm.orderForm.lines[0].quantity = 1.5;
    await wrapper.vm.saveOrder(); expect(writes()).toHaveLength(0); expect(wrapper.vm.formError).toContain('整数数量');
    wrapper.vm.orderForm.lines[0].quantity = 2; await wrapper.vm.saveOrder();
    expect(writes()[0]).toMatchObject({ method: 'post', url: `${BASE}purchase-orders/`, data: { supplier_id: 2, country_id: 3, reference_number: '重复参考号', lines: [{ sku_id: 6, quantity: 2, unit_price: null }] } });
    await wrapper.vm.actOnOrder('confirm'); expect(writes()).toHaveLength(1); expect(mocks.confirm).not.toHaveBeenCalled(); wrapper.unmount();
  });

  it('defaults supplier then product references and preserves manually entered prices on supplier changes', async () => {
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/options/') ? ok([
      { id: 6, sku: 'SKU-A', name: '甲', product_reference_price: '5', supplier_reference_price: request.params.supplier_id === 7 ? '6' : '0' },
      { id: 9, sku: 'SKU-B', name: '乙', product_reference_price: '3', supplier_reference_price: null },
    ], { count: 2 }) : ok([], { count: 0 }));
    const wrapper = createPage(); await flushPromises(); wrapper.vm.openCreate(); wrapper.vm.orderForm.supplier_id = 2; await wrapper.vm.searchSkus('');
    wrapper.vm.addLine(); wrapper.vm.orderForm.lines[0].sku_id = 6; wrapper.vm.selectOrderSku(wrapper.vm.orderForm.lines[0]);
    wrapper.vm.addLine(); wrapper.vm.orderForm.lines[1].sku_id = 9; wrapper.vm.selectOrderSku(wrapper.vm.orderForm.lines[1]);
    expect(wrapper.vm.orderSkuOptions(wrapper.vm.orderForm.lines[0]).map(item => item.id)).toEqual([6]);
    expect(wrapper.vm.orderSkuOptions(wrapper.vm.orderForm.lines[1]).map(item => item.id)).toEqual([9]);
    expect(wrapper.vm.orderForm.lines.map(line => line.unit_price)).toEqual([0, 3]);
    wrapper.vm.orderForm.lines[1].unit_price = 12; wrapper.vm.orderForm.lines[1].price_defaulted = false; wrapper.vm.orderForm.supplier_id = 7; await wrapper.vm.changeOrderSupplier();
    expect(wrapper.vm.orderForm.lines.map(line => line.unit_price)).toEqual([6, 12]); expect(wrapper.vm.orderForm.lines[0].supplier_reference_price).toBe('6'); wrapper.unmount();
  });

  it('preserves original Excel row numbers and expected version while editing imported drafts', async () => {
    mocks.requestApi.mockImplementation(async request => request.method === 'get' && request.url === `${BASE}purchase-orders/8/` ? ok(order({ source_kind: 'import', lines: [{ sku_id: 6, sku: 'SKU-A', quantity: 2, unit_price: null, import_row_number: 17 }] })) : request.method === 'get' ? ok([], { count: 0 }) : ok(order({ source_kind: 'import' })));
    const wrapper = createPage(); await flushPromises(); await wrapper.vm.openDetail({ id: 8 }); wrapper.vm.addLine(); expect(wrapper.vm.orderForm.lines).toHaveLength(2);
    expect(wrapper.vm.orderForm.lines[1].import_row_number).toBeNull();
    wrapper.vm.orderForm.lines[1].sku_id = 9;
    wrapper.vm.orderForm.lines[0].unit_price = 8; await wrapper.vm.saveOrder();
    expect(writes()[0]).toMatchObject({ method: 'patch', url: `${BASE}purchase-orders/8/`, data: { expected_version: 4, lines: [{ sku_id: 6, quantity: 2, unit_price: 8, import_row_number: 17 }, { sku_id: 9, quantity: 1, unit_price: null, import_row_number: null }] } }); expect(writes()[0].data).not.toHaveProperty('source_kind'); wrapper.unmount();
  });

  it('keeps operating procurement identity and quantities fixed while allowing price, date, and notes edits', async () => {
    const sourceOrder = order({ source_kind: 'operating', supplier_id: 7, country_id: 3, order_date: '2026-10-01', notes: '旧备注', lines: [{ id: 12, sku_id: 6, sku: 'SKU-A', name: '商品甲', quantity: 5, unit_price: null, operating_sources: [{ quantity: 5 }] }] });
    mocks.requestApi.mockImplementation(async request => request.url === `${BASE}purchase-orders/8/` ? ok(sourceOrder) : request.method === 'get' ? ok([], { count: 0 }) : ok({ ...sourceOrder, order_date: '2026-10-02', notes: '新备注' }));
    const wrapper = createPage(); await flushPromises(); await wrapper.vm.openDetail({ id: 8 });
    expect(wrapper.vm.isOperatingSource).toBe(true); expect(wrapper.text()).toContain('商品和数量固定'); expect(wrapper.findAll('button').some(button => button.text().trim() === '添加 SKU')).toBe(false);
    wrapper.vm.orderForm.lines[0].unit_price = 9; wrapper.vm.orderForm.order_date = '2026-10-02'; wrapper.vm.orderForm.notes = '新备注'; await wrapper.vm.saveOrder();
    expect(writes()[0]).toMatchObject({ method: 'patch', url: `${BASE}purchase-orders/8/`, data: { supplier_id: 7, country_id: 3, order_date: '2026-10-02', notes: '新备注', lines: [{ sku_id: 6, quantity: 5, unit_price: 9 }] } });
    mocks.requestApi.mockResolvedValue(ok({ ...sourceOrder, status: 'confirmed' }));
    await wrapper.vm.openDetail({ id: 8 });
    expect(wrapper.find('input[aria-label="采购日期"]').attributes('disabled')).toBeDefined();
    expect(wrapper.text()).not.toContain('发货与到仓回填将在后续阶段开放');
    wrapper.unmount();
  });

  it('reuses an uncertain write key, then uses a new key for a different payload', async () => {
    let attempts = 0;
    mocks.requestApi.mockImplementation(async request => request.method === 'get' ? ok([], { count: 0 }) : ++attempts === 1 ? { success: false, message: '网络中断', http_status: null } : ok(order()));
    const wrapper = createPage(); await flushPromises(); wrapper.vm.openCreate(); validDraft(wrapper.vm, 4); await wrapper.vm.saveOrder();
    expect(wrapper.vm.formError).toContain('结果尚未确认'); await wrapper.vm.saveOrder();
    const [first, retry] = writes(); expect(first.headers['Idempotency-Key']).toBe(retry.headers['Idempotency-Key']);
    wrapper.vm.orderForm.notes = '新操作'; await wrapper.vm.saveOrder(); expect(writes()[2].headers['Idempotency-Key']).not.toBe(retry.headers['Idempotency-Key']); wrapper.unmount();
  });

  it('confirms the saved version and reports creation of the background notification record', async () => {
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/confirm/') ? ok(order({ status: 'confirmed', version: 5, notification_status: 'blocked' })) : request.url === `${BASE}purchase-orders/8/` ? ok(order()) : ok([], { count: 0 }));
    const wrapper = createPage(); await flushPromises(); await wrapper.vm.openDetail({ id: 8 }); await wrapper.vm.actOnOrder('confirm');
    expect(writes()[0]).toMatchObject({ url: `${BASE}purchase-orders/8/confirm/`, data: { expected_version: 4 } }); expect(wrapper.vm.selectedOrder.status).toBe('confirmed'); expect(mocks.success).toHaveBeenCalledWith('采购已确认，已创建后台通知记录。');
    wrapper.vm.orderForm.reference_number = '修正参考'; await wrapper.vm.saveOrder();
    expect(writes()[1]).toMatchObject({ method: 'patch', url: `${BASE}purchase-orders/8/metadata/`, data: { expected_version: 5, reference_number: '修正参考', notes: '' } }); expect(writes()[1].data).not.toHaveProperty('lines'); wrapper.unmount();
  });

  it('does not overwrite a conflicting record or report it as saved', async () => {
    mocks.requestApi.mockImplementation(async request => request.method === 'get' ? request.url === `${BASE}purchase-orders/8/` ? ok(order()) : ok([], { count: 0 }) : { success: false, message: '版本冲突', http_status: 409 });
    const wrapper = createPage(); await flushPromises(); await wrapper.vm.openDetail({ id: 8 }); wrapper.vm.orderForm.notes = '修改'; await wrapper.vm.saveOrder();
    expect(wrapper.vm.selectedOrder.version).toBe(4); expect(wrapper.vm.formError).toContain('获取最新版本'); expect(mocks.success).not.toHaveBeenCalled(); wrapper.unmount();
  });

  it('cancels only saved drafts and leaves confirmed purchase details intact', async () => {
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/cancel/') ? ok(order({ status: 'cancelled', version: 5 })) : request.url === `${BASE}purchase-orders/8/` ? ok(order()) : ok([], { count: 0 }));
    const wrapper = createPage(); await flushPromises(); await wrapper.vm.openDetail({ id: 8 }); await wrapper.vm.actOnOrder('cancel');
    expect(writes()[0]).toMatchObject({ url: `${BASE}purchase-orders/8/cancel/`, data: { expected_version: 4 } }); expect(wrapper.vm.selectedOrder.status).toBe('cancelled');
    wrapper.vm.setOrder(order({ status: 'confirmed' })); await wrapper.vm.actOnOrder('cancel'); expect(writes()).toHaveLength(1); wrapper.unmount();
  });

  it('blocks saving stale references after a supplier lookup failure until refreshed', async () => {
    let unavailable = true;
    mocks.requestApi.mockImplementation(async request => request.url.endsWith('/options/') ? unavailable ? { success: false, message: '暂不可用', http_status: 503 } : ok([{ id: 6, sku: 'SKU-A', product_reference_price: '5', supplier_reference_price: '6' }], { count: 1 }) : ok([], { count: 0 }));
    const wrapper = createPage(); await flushPromises(); wrapper.vm.openCreate(); validDraft(wrapper.vm, 4); await wrapper.vm.changeOrderSupplier(); await wrapper.vm.saveOrder();
    expect(wrapper.vm.referenceRefreshFailed).toBe(true); expect(writes()).toHaveLength(0);
    unavailable = false; await wrapper.vm.changeOrderSupplier(); expect(wrapper.vm.referenceRefreshFailed).toBe(false); expect(wrapper.vm.orderForm.lines[0].unit_price).toBe(4); wrapper.unmount();
  });

  it('ignores an older detail response after a different procurement detail was opened', async () => {
    let resolveFirst;
    mocks.requestApi.mockImplementation(request => request.url === `${BASE}purchase-orders/8/` ? new Promise(resolve => { resolveFirst = resolve; }) : request.url === `${BASE}purchase-orders/9/` ? Promise.resolve(ok(order({ id: 9, number: 'PO-B' }))) : Promise.resolve(ok([], { count: 0 })));
    const wrapper = createPage(); await flushPromises(); const first = wrapper.vm.openDetail({ id: 8 }); await wrapper.vm.openDetail({ id: 9 }); resolveFirst(ok(order())); await first;
    expect(wrapper.vm.selectedOrder.number).toBe('PO-B'); wrapper.unmount();
  });
});

describe('archives and import staging', () => {
  it('submits full supplier and freight fields with versions and handles nullable transport fees', async () => {
    const wrapper = createPage(); await flushPromises(); wrapper.vm.activeTab = 'suppliers'; wrapper.vm.openArchive({ id: 2, version: 3, code: 'S2', name: '甲', tax_percent: '13.00', status: 'active', factory_address: '工厂', loading_address: '装货点', province: '广东', city: '深圳' }); await wrapper.vm.saveArchive();
    expect(writes()[0]).toMatchObject({ method: 'patch', url: `${BASE}suppliers/2/`, data: { expected_version: 3, factory_address: '工厂', loading_address: '装货点', province: '广东', city: '深圳', tax_percent: 13, contact_email: '', notes: '', status: 'active' } });
    wrapper.vm.activeTab = 'freight'; wrapper.vm.openArchive(); Object.assign(wrapper.vm.archiveForm, { code: 'F1', name: '货运甲', shipping_marks: 'MARK', address: '地址' }); await wrapper.vm.saveArchive();
    expect(writes()[1]).toMatchObject({ url: `${BASE}freight-companies/`, data: { fee_per_cbm: null, tax_percent: 0, is_active: true, shipping_marks: 'MARK', address: '地址' } }); wrapper.unmount();
  });

  it('requires a real price and sends optimistic versions for manual quotes', async () => {
    const wrapper = createPage(); await flushPromises(); wrapper.vm.activeTab = 'prices'; wrapper.vm.openArchive(); Object.assign(wrapper.vm.archiveForm, { supplier_id: 2, sku_id: 6, unit_price: null, effective_date: '2026-10-01' }); await wrapper.vm.saveArchive(); expect(writes()).toHaveLength(0);
    wrapper.vm.archiveForm.unit_price = 0; await wrapper.vm.saveArchive(); expect(writes()[0]).toMatchObject({ url: `${BASE}supplier-prices/`, data: { supplier_id: 2, sku_id: 6, unit_price: 0, expected_version: 0 } });
    wrapper.vm.openArchive({ id: 9, version: 7, supplier_id: 2, sku_id: 6, sku: 'SKU-A', unit_price: 8, effective_date: '2026-10-01' }); await wrapper.vm.saveArchive(); expect(writes()[1].data.expected_version).toBe(7); wrapper.unmount();
  });

  it('shows import errors, requires a valid preview, and commits only drafts with the job version', async () => {
    const invalid = { id: 11, version: 1, filename: 'purchase.xlsx', preview: { valid: false, rows_count: 2, groups_count: 0, errors: [{ row: 2, field: 'supplier', message: '找不到供应商' }], groups: [] } };
    const valid = { ...invalid, version: 2, preview: { valid: true, rows_count: 2, groups_count: 1, missing_prices_count: 1, errors: [], groups: [] } };
    let previews = 0;
    mocks.requestApi.mockImplementation(async request => request.url === `${BASE}imports/` ? ok(++previews === 1 ? invalid : valid) : request.url.endsWith('/commit/') ? ok({ ...valid, version: 3, committed_at: '2026-10-12', order_ids: [8] }) : ok([], { count: 0 }));
    const wrapper = createPage(); await flushPromises(); wrapper.vm.openImport(); wrapper.vm.selectImportFile({ target: { files: [new File(['book'], 'purchase.xlsx')] } }); await wrapper.vm.previewImportFile();
    expect(wrapper.vm.importJob.preview.errors[0].message).toBe('找不到供应商'); await wrapper.vm.commitImportFile(); expect(writes()).toHaveLength(1);
    await wrapper.vm.previewImportFile(); await wrapper.vm.commitImportFile(); expect(writes()[2]).toMatchObject({ url: `${BASE}imports/11/commit/`, data: { expected_version: 2 } });
    expect(wrapper.vm.importJob.order_ids).toEqual([8]); expect(writes().some(request => request.url.endsWith('/confirm/'))).toBe(false); wrapper.unmount();
  });
});


describe('procurement fulfillment workbench', () => {
  it('renders numbered stage states and keeps partial shipment in progress', () => {
    const wrapper = mount(FulfillmentProgressV2, { props: { progress: {
      stage: 'partial_shipment', ordered_quantity: 200, shipped_quantity: 130,
      unshipped_quantity: 70, dispatched_quantity: 0, received_quantity: 0
    } }, global: { stubs: { 'el-tag': { template: '<span><slot /></span>' } } } });
    expect(wrapper.text()).toContain('1'); expect(wrapper.text()).toContain('下单');
    expect(wrapper.text()).toContain('已完成'); expect(wrapper.text()).toContain('进行中');
    expect(wrapper.text()).toContain('待开始'); expect(wrapper.text()).toContain('未发 70 件');
    expect(wrapper.findAll('li')[1].classes()).toContain('active');
    expect(wrapper.findAll('li')[1].text()).not.toContain('已完成');
    wrapper.unmount();
  });
  it('does not show completed shipment when an over-shipped SKU masks another unshipped SKU', () => {
    const wrapper=mount(FulfillmentProgressV2,{props:{progress:{stage:'partial_shipment',ordered_quantity:2,shipped_quantity:2,unshipped_quantity:1,dispatched_quantity:0,received_quantity:0}},global:{stubs:{'el-tag':{template:'<span><slot /></span>'}}}});
    expect(wrapper.findAll('li')[1].classes()).toContain('active');expect(wrapper.findAll('li')[1].text()).toContain('未发 1 件');wrapper.unmount();
  });
  it('reuses actual stage counts while paging and refreshes them for explicit queries',async()=>{
    mocks.requestApi.mockImplementation(async request=>ok([order()],{count:23,workflow_counts:{all:23,pending:3,partial_shipment:6,in_transit:12,awaiting_inbound:2}}));
    const wrapper=createPage();await flushPromises();expect(wrapper.text()).toContain('23');
    await wrapper.vm.changePage(2);await flushPromises();expect(mocks.requestApi.mock.calls.at(-1)[0].params.include_workflow_counts).toBeUndefined();
    wrapper.vm.filters.order_dates=['2026-10-01','2026-10-18'];wrapper.vm.filters.supplier_id=2;await wrapper.vm.applyFilters();await flushPromises();
    expect(mocks.requestApi.mock.calls.at(-1)[0].params).toMatchObject({include_workflow_counts:'1',order_date_from:'2026-10-01',order_date_to:'2026-10-18',supplier_id:2,offset:0});wrapper.unmount();
  });
  it('filters server-side by fulfillment and country without treating confirmation as receipt', async () => {
    const wrapper=createPage();await flushPromises();
    wrapper.vm.filters.country_code='PH';await wrapper.vm.selectWorkflow('awaiting_inbound');await flushPromises();
    expect(mocks.requestApi).toHaveBeenLastCalledWith(expect.objectContaining({params:expect.objectContaining({workflow:'awaiting_inbound',country_code:'PH',offset:0})}));
    wrapper.unmount();
  });
  it('opens one order progress with related records and makes no mutations', async () => {
    const data=order({status:'confirmed',fulfillment:{stage:'partial_shipment',label:'部分发货',ordered_quantity:2,shipped_quantity:1,unshipped_quantity:1,dispatched_quantity:0,received_quantity:0},flow_relations:{shipments:[{id:4,number:'SH4',quantity:1}],batches:[],inbounds:[]}});
    mocks.requestApi.mockImplementation(async r=>r.url.endsWith('/8/')?ok(data):ok([data],{count:1}));
    const wrapper=createPage();await flushPromises();await wrapper.vm.openFlow(data);await flushPromises();
    expect(wrapper.find('[aria-label="所选采购单履约详情"]').text()).toContain('SH4');
    expect(wrapper.text()).toContain('未发 1 件');expect(writes()).toHaveLength(0);wrapper.unmount();
  });
});
