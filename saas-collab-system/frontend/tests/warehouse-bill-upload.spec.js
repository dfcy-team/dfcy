import { flushPromises, shallowMount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';

const request = vi.hoisted(() => vi.fn());
const auth = vi.hoisted(() => ({ hasPermission: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi: request, downloadApiFile: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => auth }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessageBox: { confirm } }));
import WarehouseBillUpload from '../src/components/WarehouseBillUpload.vue';

const BASE = '/api/finance/warehouse-fees/original-bills/';
const ready = { id: 'job-id', status: 'ready', file_name: '原账单.xlsx', version: 2, processed: 5,
  counts: { valid: 4, error: 1 }, count: 5, results: [], overrides: {}, summary: { country: 'PH', bill_month: '2026-09' } };
const props = { options: { countries: [{ code: 'PH', name: '菲律宾' }], warehouses: [{ id: 1, code: 'WH', name: '历史仓', country: 'PH' }], stores: [], currencies: ['CNY', 'PHP'] } };
const previewRow = { number: 1, status: 'valid', match_status: 'unmatched',
  data: { kind: 'order', country: 'PH', store_id: null, warehouse_id: 1, external_order_id: '00012345678901234567890',
    fee_item: '出库处理费', amount: '2.600000', currency: 'CNY', occurred_on: null, note: '' },
  source: { sheet: '库内操作费', row: 82, raw_store: '原店', raw_warehouse: '原仓' } };
let wrapper;
beforeEach(() => {
  vi.clearAllMocks(); auth.hasPermission.mockReturnValue(true); confirm.mockResolvedValue('confirm');
  request.mockImplementation(async config => ({ success: true, data: config.url === BASE && !config.method ? { results: [ready] } : structuredClone(ready) }));
});
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); });
async function mount() {
  wrapper = shallowMount(WarehouseBillUpload, { props, global: { stubs: {
    ElCollapse: { template: '<div data-test="mapping-panel"><slot /></div>' },
    ElCollapseItem: { props: ['title'], template: '<div><span>{{ title }}</span><slot /></div>' },
    ElButton: { template: '<button><slot /></button>' },
  } } });
  await flushPromises(); return wrapper;
}

describe('original warehouse bill uploads', () => {
  it('provides a pending-review filter and blocks unlinked-order copy from suggesting registration', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready); await flushPromises(); request.mockClear();
    await wrapper.get('[aria-label="查看待核对区"]').trigger('click');
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ params: expect.objectContaining({ status: 'error' }) }));
    const source = readFileSync('src/components/WarehouseBillUpload.vue', 'utf8');
    expect(source).toContain('未关联本地 SaaS 订单，待核对，暂不登记');
    expect(source).not.toContain('不影响登记');
  });
  it('requires explicit confirmation and permissions to register the invoice total', async () => {
    await mount(); wrapper.vm.job = { ...structuredClone(ready), summary: { ...ready.summary,
      settlement: { valid: true, total: '120.000000', currency: 'CNY' } } };
    request.mockClear(); await wrapper.vm.confirmSettlement();
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('120.000000 CNY'), '确认结算登记');
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'post',
      data: { operation: 'settle', version: 2 } }));
    wrapper.vm.job = { ...structuredClone(ready), summary: { settlement: { valid: true } } };
    auth.hasPermission.mockReturnValue(false); request.mockClear();
    await wrapper.vm.confirmSettlement(); expect(request).not.toHaveBeenCalled();
  });
  it('loads personal history without automatically uploading or creating fees', async () => {
    await mount(); expect(wrapper.vm.history).toHaveLength(1);
    expect(request.mock.calls.every(([c]) => !c.method && c.noMockFallback)).toBe(true);
  });
  it('automatically parses the selected original file but never automatically confirms import', async () => {
    await mount(); request.mockClear();
    const event = { target: { files: [new File(['xlsx'], '原账单.xlsx')], value: 'selected' } };
    await wrapper.vm.upload(event);
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'post', url: BASE, timeout: 300000, data: expect.any(FormData) }));
    const write = request.mock.calls.filter(([c]) => c.method);
    expect(write).toHaveLength(1); expect(write[0][0].data.get('options')).toBe('{}');
    expect(event.target.value).toBe('');
  });
  it('requires explicit valid-only selection and confirmation before importing drafts', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready); request.mockClear();
    await wrapper.vm.confirmImport(); expect(request).not.toHaveBeenCalled();
    wrapper.vm.validOnly = true; await wrapper.vm.confirmImport();
    expect(confirm).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'post', url: BASE + 'job-id/', data: { operation: 'import', version: 2, valid_only: true } }));
  });
  it('keeps mapping local to this job and sends its preview version on reparse', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready); wrapper.vm.settings.warehouses = { '旧仓名称': 1 }; request.mockClear();
    await wrapper.vm.reparse();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'post', url: BASE + 'job-id/', data: { operation: 'parse', version: 2, options: { warehouses: { '旧仓名称': 1 }, stores: {} } } }));
    expect(request.mock.calls.every(([c]) => c.url.startsWith(BASE))).toBe(true);
  });
  it('keeps store and warehouse mapping without manual identification fields', async () => {
    await mount(); wrapper.vm.job = { ...structuredClone(ready), summary: { ...ready.summary,
      unresolved: { warehouses: [{ name: '旧仓名称', count: 1 }], stores: [{ name: '旧店铺名称', count: 1 }] } } };
    await flushPromises();
    expect(wrapper.text()).toContain('本账单店铺与仓库映射');
    expect(wrapper.find('[aria-label="映射仓库旧仓名称"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="映射店铺旧店铺名称"]').exists()).toBe(true);
    for (const label of ['补充国家', '补充账单月份', '确认结算币种']) expect(wrapper.find(`[aria-label="${label}"]`).exists()).toBe(false);
    expect(wrapper.text()).not.toContain('补充识别信息');
    expect(wrapper.text()).not.toContain('按补充信息重新解析');
    expect(wrapper.get('[aria-label="应用本账单店铺与仓库映射"]').text()).toBe('应用映射（不导入）');
  });
  it('hides the mapping panel when no unresolved stores or warehouses remain', async () => {
    await mount(); wrapper.vm.job = { ...structuredClone(ready), summary: { ...ready.summary,
      unresolved: { warehouses: [], stores: [] } } };
    await flushPromises();
    expect(wrapper.find('[data-test="mapping-panel"]').exists()).toBe(false);
    wrapper.vm.job = { ...structuredClone(ready), status: 'failed', summary: {}, error: '账单未注明结算币种，请补充确认' };
    await flushPromises();
    expect(wrapper.find('[data-test="mapping-panel"]').exists()).toBe(false);
    expect(wrapper.find('[aria-label="确认结算币种"]').exists()).toBe(false);
    expect(wrapper.find('el-alert-stub[title="账单未注明结算币种，请补充确认"]').exists()).toBe(true);
  });
  it('preserves saved identification overrides when applying mappings without importing', async () => {
    await mount();
    const saved = { ...structuredClone(ready), overrides: { country: 'PH', bill_month: '2026-09', currency: 'CNY' },
      summary: { ...ready.summary, unresolved: { warehouses: [{ name: '旧仓名称', count: 1 }], stores: [] } } };
    request.mockResolvedValue({ success: true, data: saved });
    await wrapper.vm.selectHistory('job-id');
    wrapper.vm.settings.warehouses = { '旧仓名称': 1 }; request.mockClear();
    await wrapper.get('[aria-label="应用本账单店铺与仓库映射"]').trigger('click'); await flushPromises();
    const writes = request.mock.calls.filter(([c]) => c.method);
    expect(writes).toHaveLength(1);
    expect(writes[0][0]).toEqual(expect.objectContaining({ method: 'post', url: BASE + 'job-id/', data: {
      operation: 'parse', version: 2, options: { country: 'PH', bill_month: '2026-09', currency: 'CNY', warehouses: { '旧仓名称': 1 }, stores: {} },
    } }));
  });
  it('rejects oversize or non-xlsx files without sending them', async () => {
    await mount(); request.mockClear();
    await wrapper.vm.upload({ target: { files: [{ name: 'huge.xlsx', size: 129 * 1024 * 1024 }] } });
    expect(request).not.toHaveBeenCalled(); expect(wrapper.vm.error).toContain('128MB');
  });
  it('blocks handlers after losing import permission', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready); wrapper.vm.validOnly = true;
    auth.hasPermission.mockReturnValue(false); request.mockClear();
    await wrapper.vm.confirmImport(); await wrapper.vm.reparse();
    expect(request).not.toHaveBeenCalled();
  });
  it('clears polling when the dialog is destroyed', async () => {
    vi.useFakeTimers(); await mount(); wrapper.vm.job = { ...ready, status: 'parsing' };
    request.mockResolvedValue({ success: true, data: { ...ready, status: 'parsing' } });
    await wrapper.vm.refresh(); request.mockClear(); wrapper.unmount();
    await vi.advanceTimersByTimeAsync(10000); expect(request).not.toHaveBeenCalled();
    wrapper = null;
  });
  it('preserves the template path and makes original bills the default', () => {
    const source = readFileSync('src/views/finance/WarehouseFees.vue', 'utf8');
    expect(source).toContain("const importMode = ref('original')");
    expect(source).toContain('标准登记模板'); expect(source).toContain('原始仓库账单（自动解析）');
  });
  it('edits the effective row as text, sends a version, and never imports automatically', async () => {
    await mount(); wrapper.vm.job = { ...structuredClone(ready), counts: { valid: 1 }, results: [structuredClone(previewRow)] };
    wrapper.vm.startEdit(wrapper.vm.job.results[0]);
    wrapper.vm.editForm.amount = '3.123456'; wrapper.vm.editReason = '核对金额';
    expect(wrapper.vm.job.results[0].data.amount).toBe('2.600000');
    request.mockClear(); await wrapper.vm.saveEdit();
    const writes = request.mock.calls.filter(([c]) => c.method);
    expect(writes).toHaveLength(1);
    expect(writes[0][0].data).toEqual({ operation: 'edit', version: 2,
      rows: [{ number: 1, changes: { amount: '3.123456' } }], reason: '核对金额' });
    expect(wrapper.vm.editRow).toBe(null);
  });
  it('keeps unsaved row edits after save failure and prevents import while editing', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready); wrapper.vm.startEdit(previewRow);
    wrapper.vm.editForm.external_order_id = '00009876543210987654321'; wrapper.vm.editReason = '核对订单';
    request.mockRejectedValue(new Error('保存失败')); request.mockClear();
    await wrapper.vm.confirmImport(); expect(request).not.toHaveBeenCalled();
    await wrapper.vm.saveEdit();
    expect(wrapper.vm.editForm.external_order_id).toBe('00009876543210987654321');
    expect(wrapper.vm.editRow.number).toBe(1); expect(wrapper.vm.error).toContain('保存失败');
  });
  it('limits batch edits to the explicitly selected rows and allowed fields', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready);
    wrapper.vm.selectedRows = [structuredClone(previewRow), { ...structuredClone(previewRow), number: 3 }];
    wrapper.vm.batchField = 'warehouse_id'; wrapper.vm.batchValue = 1; wrapper.vm.batchReason = '已核实仓库';
    request.mockClear(); await wrapper.vm.saveBatch();
    expect(confirm).toHaveBeenCalledOnce();
    const write = request.mock.calls.find(([c]) => c.method)[0];
    expect(write.data.rows).toEqual([{ number: 1, changes: { warehouse_id: 1 } }, { number: 3, changes: { warehouse_id: 1 } }]);
    wrapper.vm.selectedRows = [previewRow]; wrapper.vm.batchField = 'amount'; request.mockClear();
    await wrapper.vm.saveBatch(); expect(request).not.toHaveBeenCalled();
  });
  it('locks previews after any row has been imported or while a worker is running', async () => {
    await mount(); wrapper.vm.job = { ...structuredClone(ready), counts: { created: 1, valid: 3 } };
    wrapper.vm.startEdit(previewRow); expect(wrapper.vm.editRow).toBe(null);
    wrapper.vm.job = { ...structuredClone(ready), status: 'parsing' };
    wrapper.vm.startEdit(previewRow); expect(wrapper.vm.editRow).toBe(null);
    auth.hasPermission.mockReturnValue(false); wrapper.vm.job = structuredClone(ready);
    wrapper.vm.startEdit(previewRow); expect(wrapper.vm.editRow).toBe(null);
  });
  it('requires confirmation before discarding dirty edits and cleans unload listeners', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready); wrapper.vm.startEdit(previewRow); wrapper.vm.editForm.note = '未保存';
    confirm.mockRejectedValue('cancel');
    expect(await wrapper.vm.canLeave()).toBe(false);
    expect(wrapper.vm.editRow).not.toBe(null);
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    confirm.mockResolvedValue('confirm'); expect(await wrapper.vm.canLeave()).toBe(true);
    wrapper.unmount(); wrapper = null;
    const clean = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
  });
  it('uses null for a cleared date and blocks a batch store assignment to country fees', async () => {
    await mount(); wrapper.vm.job = structuredClone(ready);
    wrapper.vm.startEdit({ ...previewRow, data: { ...previewRow.data, occurred_on: '2026-09-01' } });
    wrapper.vm.editForm.occurred_on = ''; request.mockClear(); await wrapper.vm.saveEdit();
    expect(request.mock.calls.find(([c]) => c.method)[0].data.rows).toEqual([{ number: 1, changes: { occurred_on: null } }]);
    wrapper.vm.selectedRows = [{ ...previewRow, data: { ...previewRow.data, kind: 'other' } }];
    wrapper.vm.batchField = 'store_id'; wrapper.vm.batchValue = 1; wrapper.vm.batchReason = '不应设置'; request.mockClear();
    await wrapper.vm.saveBatch(); expect(request).not.toHaveBeenCalled(); expect(wrapper.vm.error).toContain('国家级');
  });
});
