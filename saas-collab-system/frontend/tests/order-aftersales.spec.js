import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest';

const request = vi.hoisted(() => vi.fn());
const auth = vi.hoisted(() => ({ hasPermission: vi.fn() }));
vi.mock('../src/api/request', () => ({ requestApi: request, downloadApiFile: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessageBox: { confirm: vi.fn(), prompt: vi.fn() } }));
import OrderAftersales from '../src/views/sales-management/OrderAftersales.vue';

const BASE = '/api/internal/commerce/aftersales/';
let wrapper;
const success = data => ({ success: true, data });
beforeEach(() => {
  vi.clearAllMocks(); auth.hasPermission.mockReturnValue(true);
  request.mockImplementation(async config => {
    if (config.url.endsWith('settings/')) return success({ version: 0, interval_minutes: 60, is_enabled: false, warehouse_bound: false });
    if (config.url.endsWith('options/')) return success({ stores: [] });
    if (config.url.endsWith('import/')) return success({ warehouses: [] });
    return success({ count: 0, results: [] });
  });
});
afterEach(() => wrapper?.unmount());
async function mount() {
  wrapper = shallowMount(OrderAftersales, { global: { stubs: {
    ElButton: { template: '<button><slot /></button>' },
    ElDrawer: { template: '<div><slot /></div>' }, ElDialog: { template: '<div><slot /></div>' },
    ElForm: { template: '<form><slot /></form>' }, ElFormItem: { template: '<label><slot /></label>' },
  } } });
  await flushPromises(); return wrapper;
}

describe('order aftersales workspace', () => {
  it('saves a reviewed warehouse return number separately from the tracking number', async () => {
    await mount();
    const detail = { source_key: 'refund:9', store: { name: 'Store' }, expected_skus: { 'SKU-A': 1 },
      tracking: { version: 3, requires_return: true, warehouse_return_no: 'RMA-9', tracking_no: 'TRACK-9' }, history: [] };
    request.mockImplementation(async config => config.url.includes('cases/') ? success(detail) : success({ count: 0, results: [] }));
    await wrapper.vm.openCase('refund:9');
    expect(wrapper.vm.review.warehouse_return_no).toBe('RMA-9');
    wrapper.vm.review.reason = '核对百世单号';
    await wrapper.vm.saveCase();
    expect(request.mock.calls.find(([config]) => config.method === 'patch')[0].data).toMatchObject({
      warehouse_return_no: 'RMA-9', tracking_no: 'TRACK-9', expected_version: 3,
    });
    request.mockResolvedValue(success({ ...detail, source_key: 'refund:10', tracking: {} }));
    await wrapper.vm.openCase('refund:10');
    expect(wrapper.vm.review.warehouse_return_no).toBe('');
  });
  it('does not carry a previous warehouse query result into another case', async () => {
    await mount();
    wrapper.vm.feedback = '本次未查到退货单，不代表未到仓。';
    request.mockResolvedValue(success({ source_key: 'refund:9', store: { name: 'Store' },
      expected_skus: {}, tracking: {}, history: [], return_status: 'pending' }));
    await wrapper.vm.openCase('refund:9');
    expect(wrapper.vm.feedback).toBe('');
    expect(wrapper.vm.detail.source_key).toBe('refund:9');
  });
  it('queries only the selected case and reports incomplete warehouse checks', async () => {
    await mount();
    const detail = { source_key: 'cancelled:7', store: { name: 'Store' }, expected_skus: {}, tracking: {}, history: [], return_status: 'pending' };
    wrapper.vm.detail = detail;
    request.mockImplementation(async config => config.method === 'post' ? success({ status: 'incomplete' }) :
      config.url.includes('cases/') ? success(detail) : success({ count: 0, results: [] }));
    await wrapper.vm.queryReturn();
    const calls = request.mock.calls.filter(([config]) => config.method === 'post');
    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toMatchObject({ url: BASE + 'cases/cancelled%3A7/', data: {} });
    expect(wrapper.vm.feedback).toContain('未自动关联');
    expect(wrapper.vm.busy).toBe(false);
  });
  it('renames the workspace and performs only reads on entry', async () => {
    await mount(); expect(wrapper.find('h1').text()).toBe('订单售后');
    expect(request.mock.calls.every(([config]) => !config.method && config.noMockFallback)).toBe(true);
    expect(wrapper.vm.settings.warehouse_bound).toBe(false);
    expect(wrapper.vm.fullAccess).toBe(true);
  });
  it('saves the adjustable hourly setting without binding or enabling a warehouse', async () => {
    await mount(); wrapper.vm.settings.interval_minutes = 120;
    await wrapper.vm.saveSettings();
    const config = request.mock.calls.find(([item]) => item.method === 'patch')[0];
    expect(config.data).toEqual({ expected_version: 0, interval_minutes: 120, is_enabled: false });
    expect(config.data).not.toHaveProperty('authorization_id');
    expect(request.mock.calls.some(([item]) => item.url.endsWith('sync/'))).toBe(false);
  });
  it('does not call management endpoints for a view-only operator', async () => {
    auth.hasPermission.mockReturnValue(false); await mount();
    expect(wrapper.vm.fullAccess).toBe(false);
    expect(request.mock.calls.some(([item]) => item.url.endsWith('settings/') || item.url.endsWith('import/'))).toBe(false);
  });
  it('does not show a lone section-switch button to a view-only operator', async () => {
    auth.hasPermission.mockReturnValue(false); await mount();
    expect(wrapper.find('[aria-label="订单售后分区"]').exists()).toBe(false);
    expect(wrapper.findAll('button').some(button => button.text() === '订单售后')).toBe(false);
  });
  it('uses tabs to switch between aftersales and unmatched receipts', async () => {
    await mount(); request.mockClear();
    const tabs = wrapper.findComponent({ name: 'ElTabs' });
    expect(tabs.exists()).toBe(true);
    tabs.vm.$emit('tab-change', 'receipts'); await flushPromises();
    expect(wrapper.vm.tab).toBe('receipts');
    expect(request.mock.calls.at(-1)[0].url).toBe(BASE + 'receipts/');
    tabs.vm.$emit('tab-change', 'cases'); await flushPromises();
    expect(wrapper.vm.tab).toBe('cases');
    expect(request.mock.calls.at(-1)[0].url).toBe(BASE);
    expect(request.mock.calls.every(([config]) => !config.method)).toBe(true);
  });
  it('shows missing-data and not-required quantities without pretending they are zero received', async () => {
    await mount(); expect(wrapper.vm.quantityLabel({ return_status: 'unknown' })).toBe('待确认');
    expect(wrapper.vm.quantityLabel({ return_status: 'not_required' })).toBe('不适用');
    expect(wrapper.vm.quantityLabel({ return_status: 'partial', tracking: { lines: [{ received: 2, expected: 3 }] } })).toBe('2 / 3');
  });
  it('keeps an API failure distinct from a successful empty result', async () => {
    await mount(); request.mockResolvedValue({ success: false, message: '读取失败，请稍后重试。' });
    await wrapper.vm.load(); expect(wrapper.vm.error).toContain('读取失败'); expect(wrapper.vm.loading).toBe(false);
  });
  it('previews an export without confirming or mutating records', async () => {
    await mount(); wrapper.vm.importFile = new File(['data'], 'warehouse.csv');
    request.mockResolvedValue(success({ documents: 1, lines: 1, sha256: 'test-digest', preview: [] }));
    await wrapper.vm.previewImport();
    const config = request.mock.calls.find(([item]) => item.method === 'post')[0];
    expect(config.url).toBe(BASE + 'import/'); expect(config.data.get('operation')).toBe('preview');
    expect(config.data.has('sha256')).toBe(false);
  });
  it('does not accept a late list response after switching to receipt matching', async () => {
    await mount(); let resolve;
    request.mockImplementation(config => config.url === BASE ? new Promise(done => { resolve = done; }) : Promise.resolve(success({ count: 1, results: [{ id: 9, return_no: 'WMS-1' }] })));
    const first = wrapper.vm.load(); wrapper.vm.changeTab('receipts'); await flushPromises();
    resolve(success({ count: 1, results: [{ source_key: 'cancelled:1' }] })); await first; await flushPromises();
    expect(wrapper.vm.rows[0].return_no).toBe('WMS-1');
  });
});
