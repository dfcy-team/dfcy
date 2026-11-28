import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { canAccessPath, filterMenuItems, flattenMenuItems } from '../src/router/menu';

const request = vi.hoisted(() => vi.fn());
const auth = vi.hoisted(() => ({ hasPermission: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi: request, downloadApiFile: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn() }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessageBox: { confirm, prompt: vi.fn() } }));
import WarehouseFees from '../src/views/finance/WarehouseFees.vue';

const base = '/api/finance/warehouse-fees/';
const row = { id: 1, kind: 'order', status: 'draft', version: 1, country: 'PH', store_id: 1, warehouse_id: 1,
  external_order_id: 'ORDER-1', bill_number: 'B-1', bill_month: '2026-09', reference: 'WMS-1', fee_item: '订单处理费',
  amount: '2.400000', currency: 'CNY', original_amount: null, original_currency: '', exchange_rate: null,
  rate_date: null, rate_source: '', occurred_on: null, note: '', match_status: 'unmatched', source: { type: 'manual' }, audit: [] };
beforeEach(() => {
  vi.clearAllMocks(); auth.hasPermission.mockReturnValue(true); confirm.mockResolvedValue('confirm');
  request.mockImplementation(async config => {
    if (config.url.endsWith('options/')) return { success: true, data: { countries: [{ code: 'PH', name: '菲律宾' }], warehouses: [], stores: [], currencies: ['CNY', 'PHP'] } };
    if (config.url === base && !config.method) return { success: true, data: { results: [row], count: 1, registered_totals: [] } };
    return { success: true, data: { ...row } };
  });
});

describe('warehouse fee registration', () => {
  it('creates either fee type in the compact dialog and returns saved drafts to that list', async () => {
    const wrapper = shallowMount(WarehouseFees, { global: { stubs: {
      AppPage: { template:'<div><slot /></div>' },
      ElDialog: { template:'<div><slot name="header" /><slot /></div>' },
      ElForm: { template:'<form><slot /></form>' },
      ElFormItem: { props:['label'], template:'<label>{{ label }}<slot /></label>' },
    } } });
    await flushPromises(); wrapper.vm.newFee(); await flushPromises();
    const dialog = wrapper.find('.warehouse-create-dialog');
    expect(dialog.attributes('width')).toBe('min(600px, calc(100vw - 32px))');
    expect(dialog.text()).toContain('费用类型');
    expect(dialog.text()).toContain('订单号／预约单号／包裹号');
    expect(dialog.text()).not.toContain('费用归属');
    expect(dialog.text()).not.toContain('备注');
    wrapper.vm.form.external_order_id = 'PACKAGE001';
    wrapper.vm.form.kind = 'other'; wrapper.vm.changeNewFeeKind(); await flushPromises();
    expect(dialog.text()).toContain('费用名称');
    expect(dialog.text()).not.toContain('订单号／预约单号／包裹号');
    expect(wrapper.vm.form.external_order_id).toBe('');
    Object.assign(wrapper.vm.form, {country:'PH',warehouse_id:1,fee_item:'仓储费',amount:'6',bill_month:'2026-10'});
    await wrapper.vm.save();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method:'post', url:base, data:expect.objectContaining({kind:'other',fee_item:'仓储费',external_order_id:'',amount:'6'}) }));
    expect(wrapper.vm.editor).toBe(false);
    expect(wrapper.vm.kind).toBe('other');
    expect(wrapper.vm.filters.status).toBe('draft');
    wrapper.unmount();
  });
  it('opens original-file parsing by default, without requiring a template', async () => {
    const wrapper = shallowMount(WarehouseFees, { global: { stubs:{ AppPage:{template:'<div><slot /><slot name="action" /></div>'}, ElDialog:{template:'<div class="batch-dialog"><slot name="header" /><slot /></div>'} } } }); await flushPromises();
    wrapper.vm.openImport();
    await flushPromises();
    expect(wrapper.vm.importVisible).toBe(true);
    expect(wrapper.find('.warehouse-batch-dialog').attributes('fullscreen')).not.toBe('true');
    expect(wrapper.find('.warehouse-batch-dialog').attributes('width')).toBe('min(1200px, calc(100vw - 32px))');
    expect(wrapper.find('warehouse-bill-upload-stub').exists()).toBe(true);
    expect(wrapper.find('.batch-dialog').text()).not.toContain('简化登记模板');
    expect(wrapper.find('el-radio-group-stub').exists()).toBe(false);
    wrapper.vm.showBatch({results:[{status:'created',row:2}]}); await flushPromises();
    expect(wrapper.find('warehouse-bill-upload-stub').exists()).toBe(false);
    expect(wrapper.find('.warehouse-batch-dialog').text()).toContain('本次新增1条草稿');
    wrapper.vm.openImport(); await flushPromises();
    expect(wrapper.find('warehouse-bill-upload-stub').exists()).toBe(true);
    wrapper.unmount();
  });
  it('submits only simple fields and keeps its retry identity', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    wrapper.vm.newFee();
    Object.assign(wrapper.vm.form, { country: 'PH', warehouse_id: 1, external_order_id: 'PACKAGE001', amount: '30', bill_month: '2026-10' });
    const reference = wrapper.vm.form.reference;
    request.mockImplementation(async config => config.method ? { success: false, message: '网络失败' } : { success: true, data: row });
    await wrapper.vm.save(); await wrapper.vm.save();
    const writes = request.mock.calls.map(([c]) => c).filter(c => c.method === 'post');
    expect(writes).toHaveLength(2);
    expect(writes[0].data).toMatchObject({ registration_mode: 'cny_simple', amount: '30', reference, external_order_id: 'PACKAGE001' });
    expect(writes[0].data).not.toHaveProperty('store_id');
    expect(writes[0].data).not.toHaveProperty('exchange_rate');
    expect(writes[1].data.reference).toBe(reference);
    wrapper.unmount();
  });
  it('restores original CNY amount through the audited correction API', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    wrapper.vm.selected = { ...row, status: 'registered', amount: '10', source: { registration_mode: 'cny_simple', registration_original_amount: '30' } };
    wrapper.vm.beginEdit(); wrapper.vm.restoreOriginalAmount();
    await wrapper.vm.save();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ url: base + '1/correct/', data: {
      expected_version: 1, changes: { amount: '30', note: '' }, reason: '恢复原登记金额',
    } }));
    wrapper.unmount();
  });
  it('uses an independent menu grant and route', () => {
    const user = { user_type: 'internal', permissions: ['finance.warehouse_fees.view'] };
    expect(canAccessPath(user, '/finance/warehouse-fees')).toBe(true);
    expect(flattenMenuItems(filterMenuItems(user)).some(item => item.path === '/finance/warehouse-fees')).toBe(true);
    expect(canAccessPath({ user_type: 'internal', permissions: ['finance.view'] }, '/finance/warehouse-fees')).toBe(false);
  });
  it('loads only scoped live data and keeps CNY independent of store currency', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    expect(wrapper.vm.rows).toHaveLength(1);
    expect(request.mock.calls.every(([config]) => config.noMockFallback === true)).toBe(true);
    wrapper.vm.newFee();
    expect(wrapper.vm.form.currency).toBe('CNY');
    expect(wrapper.vm.form.original_amount).toBe('');
    wrapper.unmount();
  });
  it('confirms registration without a payment or order mutation API', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    wrapper.vm.selected = { ...row, match_status: 'matched' };
    await wrapper.vm.singleAction('register');
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ url: base + '1/register/', method: 'post', data: { expected_version: 1, reason: '' } }));
    expect(request.mock.calls.some(([config]) => /payments|sales-orders|warehouse-api/.test(config.url))).toBe(false);
    wrapper.unmount();
  });
  it('holds unmatched and ambiguous order fees instead of registering them', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    for (const match_status of ['unmatched', 'ambiguous']) {
      wrapper.vm.selected = { ...row, match_status };
      wrapper.vm.selection = [{ ...row, match_status }];
      request.mockClear(); confirm.mockClear();
      await wrapper.vm.singleAction('register'); await wrapper.vm.registerSelection();
      expect(request).not.toHaveBeenCalled(); expect(confirm).not.toHaveBeenCalled();
      expect(wrapper.vm.canRegister({ ...row, match_status })).toBe(false);
    }
    expect(wrapper.vm.canRegister({ ...row, kind: 'other', match_status: 'not_applicable' })).toBe(true);
    wrapper.unmount();
  });
  it('blocks unauthorized handlers rather than relying on hidden buttons', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    request.mockClear(); auth.hasPermission.mockReturnValue(false);
    wrapper.vm.newFee(); await wrapper.vm.save(); await wrapper.vm.registerSelection();
    expect(request).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('preserves saved result when subsequent list refresh fails', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises(); wrapper.vm.newFee();
    Object.assign(wrapper.vm.form, row);
    request.mockImplementation(async config => {
      if (!config.method && config.url === base) throw new Error('list unavailable');
      return { success: true, data: { ...row } };
    });
    await wrapper.vm.save();
    expect(wrapper.vm.selected.id).toBe(1);
    expect(wrapper.vm.editMode).toBe(false);
    expect(wrapper.vm.error).toContain('已保存');
    wrapper.unmount();
  });
  it('exposes both fee types and explicit preview/confirmation semantics', () => {
    const source = readFileSync('src/views/finance/WarehouseFees.vue', 'utf8');
    for (const text of ['label="仓库处理费"', 'label="其他处理费"', '导入记录', '不代表已经付款', '国家级费用', 'YYYY-MM-DD']) expect(source).toContain(text);
    expect(source).not.toContain('保存成功即付款');
  });
  it('protects unfinished original-bill edits when closing the workbench', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    const canLeave = vi.fn().mockResolvedValue(false), done = vi.fn();
    wrapper.vm.originalBill = { canLeave };
    await wrapper.vm.beforeImportClose(done); expect(done).not.toHaveBeenCalled();
    canLeave.mockResolvedValue(true); await wrapper.vm.beforeImportClose(done); expect(done).toHaveBeenCalledOnce();
    wrapper.unmount();
  });
  it('blocks missing warehouses and system supplements from manual actions', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    expect(wrapper.vm.canRegister({ ...row, kind:'other', warehouse_id:null })).toBe(false);
    wrapper.vm.selected = { ...row, match_status:'matched', source:{type:'warehouse_file_supplement'} };
    request.mockClear();
    wrapper.vm.beginEdit(); await wrapper.vm.save(); await wrapper.vm.singleAction('void');
    expect(wrapper.vm.canRegister(wrapper.vm.selected)).toBe(false);
    expect(request).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('requires a correction reason and preserves six decimal places for new file fees', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    wrapper.vm.selected = { ...row, source:{registration_mode:'file_settlement_v2',registration_original_amount:'2.123456'} };
    wrapper.vm.beginEdit(); wrapper.vm.form.note = '核对备注'; request.mockClear();
    await wrapper.vm.save(); expect(request).not.toHaveBeenCalled();
    wrapper.vm.correctionReason = '保留金额，仅补充备注'; await wrapper.vm.save();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({data:expect.objectContaining({changes:{amount:'2.400000',note:'核对备注'}})}));
    wrapper.unmount();
  });
});
