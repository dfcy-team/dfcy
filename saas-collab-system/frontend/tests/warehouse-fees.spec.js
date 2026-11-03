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
    for (const text of ['订单处理费', '仓库其他处理费', '导入记录', '校验预览（不导入）', '确认导入草稿', '不代表已付款', '国家级费用', 'YYYY-MM-DD']) expect(source).toContain(text);
    expect(source).not.toContain('保存成功即付款');
  });
  it('protects unfinished original-bill edits when closing or changing the upload mode', async () => {
    const wrapper = shallowMount(WarehouseFees); await flushPromises();
    const canLeave = vi.fn().mockResolvedValue(false), done = vi.fn();
    wrapper.vm.originalBill = { canLeave };
    await wrapper.vm.beforeImportClose(done); expect(done).not.toHaveBeenCalled();
    await wrapper.vm.changeImportMode('template'); expect(wrapper.vm.importMode).toBe('original');
    canLeave.mockResolvedValue(true); await wrapper.vm.beforeImportClose(done); expect(done).toHaveBeenCalledOnce();
    await wrapper.vm.changeImportMode('template'); expect(wrapper.vm.importMode).toBe('template');
    wrapper.unmount();
  });
});
