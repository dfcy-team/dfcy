import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ElementPlus from 'element-plus';
const request = vi.hoisted(() => vi.fn());
const confirm = vi.hoisted(() => vi.fn());
vi.mock('../src/api/request', () => ({ requestApi: request }));
vi.mock('element-plus', async original => ({ ...await original(), ElMessageBox: { confirm } }));
import WarehouseBillFormat from '../src/components/WarehouseBillFormat.vue';

let wrapper;
const sample = { name: '结算单', sample: [
  { row: 1, cells: { A: '标题' } }, { row: 7, cells: { A: '项目', B: '金额' } },
] };
beforeEach(() => {
  request.mockReset();
  confirm.mockReset();
  request.mockImplementation(async c => ({ success: true, data: c.url.endsWith('format-rules/')
    ? { results: [] } : c.method === 'post' ? { items: [
      { row: 8, item: '出库', amount: '4' }, { row: 9, item: '入库', amount: '6' },
      { row: 10, item: '合计', amount: '10' },
    ] } : { sheets: [sample] } }));
});
afterEach(() => wrapper?.unmount());
async function setup(disabled = false) {
  wrapper = mount(WarehouseBillFormat, { props: {
    disabled, job: { id: 'sample-job', summary: { country: 'PH', bill_month: '2026-10', settlement_warehouse_id: 1 } },
    options: { countries: [{ code: 'PH', name: '菲律宾' }], warehouses: [{ id: 1, code: 'WH', name: '测试仓', country: 'PH' }] },
  }, global: { plugins: [ElementPlus] } });
  await flushPromises();
}
describe('warehouse original file format configuration', () => {
  it('loads sheets after its parent finishes polling instead of leaving an empty editor', async () => {
    await setup(true);
    expect(request).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('正在读取原文件工作表');
    await wrapper.setProps({disabled:false}); await flushPromises();
    expect(wrapper.vm.loaded).toBe(true);
    expect(wrapper.vm.specs.map(s => s.name)).toEqual(['结算单']);
    expect(wrapper.get('nav').text()).toContain('结算单');
    expect(wrapper.get('nav').text()).toContain('待配置');
    expect(wrapper.text()).toContain('工作表配置 0 / 1');
    expect(wrapper.findAll('button').find(b => b.text() === '解析预览（不登记）').element.disabled).toBe(true);
  });
  it('blocks empty or incomplete rules and allows retry after a sample read failure', async () => {
    request.mockResolvedValue({success:true,data:{sheets:[]}});
    await setup();
    expect(wrapper.vm.loaded).toBe(false);
    expect(wrapper.text()).toContain('未读取到工作表');
    request.mockClear(); await wrapper.vm.saveRule(); wrapper.vm.preview();
    expect(request).not.toHaveBeenCalled(); expect(wrapper.emitted('preview')).toBeUndefined();
    request.mockImplementation(async c => ({success:true,data:c.url.endsWith('format-rules/') ? {results:[]} : {sheets:[sample]}}));
    await wrapper.findAll('button').find(b => b.text() === '重新读取工作表').trigger('click'); await flushPromises();
    expect(wrapper.vm.loaded).toBe(true);
    request.mockClear(); await wrapper.vm.saveRule(); wrapper.vm.preview();
    expect(request).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('请完成每个工作表');
  });
  it('protects unsaved configuration and blocks leaving during processing', async () => {
    await setup(); expect(await wrapper.vm.canLeave()).toBe(true);
    wrapper.vm.spec.kind = 'order';
    confirm.mockRejectedValue('cancel');
    expect(await wrapper.vm.canLeave()).toBe(false);
    confirm.mockResolvedValue('confirm');
    expect(await wrapper.vm.canLeave()).toBe(true);
    wrapper.vm.busy = true; expect(await wrapper.vm.canLeave()).toBe(false);
  });
  it('keeps the entered header and exact columns when loading settlement items', async () => {
    await setup(); wrapper.vm.spec.kind = 'settlement'; await flushPromises();
    const input = wrapper.findAll('input[role="spinbutton"]')[0];
    await input.setValue('7'); await input.trigger('change'); await input.trigger('blur');
    expect(wrapper.vm.spec.header).toBe(7);
    expect(wrapper.vm.columns.map(c => c.column)).toEqual(['A', 'B']);
    wrapper.vm.spec.columns = { item: 'A', amount: 'B' };
    await wrapper.vm.loadItems();
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'post',
      data: { spec: expect.objectContaining({ header: 7, columns: { item: 'A', amount: 'B' } }) } }));
    expect(input.element.value).toBe('7');
    expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('待核对');
    wrapper.vm.spec.items = { 出库: { role: 'order' }, 入库: { role: 'other' }, 合计: { role: 'total' } };
    expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('已配置');
    wrapper.vm.spec.items.入库 = { role: 'ignore', reason: '' };
    expect(wrapper.vm.sheetState(wrapper.vm.spec)).toBe('待核对');
  });
  it('saves server rules with current-file month only in preview and never registers fees', async () => {
    await setup();
    wrapper.vm.spec.kind = 'order'; wrapper.vm.spec.header = 7;
    wrapper.vm.spec.columns = { number: 'A', amount: 'B' };
    wrapper.vm.ruleName = '新格式';
    request.mockClear(); await wrapper.vm.saveRule();
    const writes = request.mock.calls.filter(([c]) => c.method === 'post');
    expect(writes).toHaveLength(1);
    expect(writes[0][0].url).toBe('/api/finance/warehouse-fees/format-rules/');
    expect(writes[0][0].data).toMatchObject({ name: '新格式', warehouse_id: 1,
      config: { schema_version: 3, sheets: [expect.objectContaining({ header: 7, expected: { A: '项目', B: '金额' } })] } });
    expect(writes[0][0].data).not.toHaveProperty('bill_month');
    wrapper.vm.preview();
    expect(wrapper.emitted('preview')[0][0]).toMatchObject({ bill_month: '2026-10', warehouse_id: 1 });
  });
});
