import { beforeEach, describe, expect, it, vi } from 'vitest';
import { computed, h, inject, provide } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(), options: vi.fn(), create: vi.fn(), update: vi.fn(), stale: false,
  requestApi: vi.fn(), messageError: vi.fn(), messageSuccess: vi.fn(), messageWarning: vi.fn(),
  newKey: vi.fn(), keyNumber: 0,
}));
vi.mock('../src/api/supplyWarehousesV2', () => ({
  fetchSupplyWarehouses: mocks.fetch, fetchSupplyWarehouseOptions: mocks.options,
  createSupplyWarehouse: mocks.create, updateSupplyWarehouse: mocks.update,
  createSupplyWarehouseIdempotencyKey: mocks.newKey,
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ authorizationStale: mocks.stale }) }));
vi.mock('../src/api/request', () => ({ requestApi: mocks.requestApi }));
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, ElMessage: { error: mocks.messageError, success: mocks.messageSuccess, warning: mocks.messageWarning } };
});
import SupplyWarehouseArchiveV2 from '../src/components/supply-chain/SupplyWarehouseArchiveV2.vue';

const rows = [{ id: 4, version: 3, code: 'system-4', name: '仓库四', country_code: 'US', warehouse_type: 'owned',
  service_platform_name: '', status: 'active', address: '', region: '', legacy_codes: ['OLD-4'], notes: '', can_manage: true,
  wms_mappings: [{ provider: 'safe-provider', external_warehouse_code: 'WMS-4', external_warehouse_region: 'US', status: 'active' }] }];

const stubs = {
  'el-input': { props: ['modelValue', 'disabled', 'placeholder', 'type'], emits: ['update:modelValue', 'keyup', 'clear'], template: '<textarea v-if="type === \'textarea\'" :value="modelValue" :disabled="disabled" :placeholder="placeholder" @input="$emit(\'update:modelValue\',$event.target.value)" /><input v-else :value="modelValue" :disabled="disabled" :placeholder="placeholder" @input="$emit(\'update:modelValue\',$event.target.value)" />' },
  'el-select': { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\',$event.target.value)"><slot /></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>' },
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-tag': { template: '<span><slot /></span>' },
  'el-table': { props: ['data'], setup(props, { slots }) { provide('warehouseRows', computed(() => props.data)); return () => h('div', slots.default?.()); }, directives: { loading: () => {} } },
  'el-table-column': { setup(_, { slots }) { const data = inject('warehouseRows'); return () => h('div', data.value.flatMap((row) => slots.default?.({ row }) || [])); } },
  'el-pagination': { template: '<nav />' },
  'el-dialog': { props: ['modelValue', 'title'], template: '<section v-if="modelValue"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' },
  'el-form': { template: '<div><slot /></div>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
};

describe('supply warehouse archive', () => {
  beforeEach(() => {
    mocks.stale = false;
    mocks.messageError.mockReset(); mocks.messageSuccess.mockReset(); mocks.messageWarning.mockReset();
    mocks.requestApi.mockReset().mockResolvedValue({ success: true });
    mocks.keyNumber = 0;
    mocks.newKey.mockReset().mockImplementation(() => `warehouse-key-${++mocks.keyNumber}`);
    mocks.options.mockReset().mockResolvedValue({ success: true, data: { countries: [{ code: 'us', name: '美国', country_code: 'US' }], service_platforms: [] } });
    mocks.fetch.mockReset().mockResolvedValue({ success: true, data: rows, count: 1, can_create: true });
    mocks.update.mockReset().mockResolvedValue({ success: true, data: rows[0] });
    mocks.create.mockReset().mockResolvedValue({ success: true, data: rows[0] });
  });

  it('shows legacy aliases separately from the safe WMS identity fields', async () => {
    const wrapper = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    expect(wrapper.text()).toContain('OLD-4');
    expect(wrapper.text()).toContain('WMS-4');
    expect(wrapper.text()).toContain('仓库代码：');
    expect(wrapper.text()).not.toContain('credential');
    wrapper.unmount();
  });

  it('honors server can_manage and blocks edit controls after authorization becomes stale', async () => {
    mocks.fetch.mockResolvedValueOnce({ success: true, data: [{ ...rows[0], can_manage: false }], count: 1, can_create: false });
    const wrapper = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    const edit = wrapper.findAll('button').find((button) => button.text().includes('编辑业务资料'));
    expect(edit.attributes('disabled')).toBeDefined();
    wrapper.unmount();

    mocks.stale = true;
    const stale = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    expect(stale.findAll('button').find((button) => button.text().includes('编辑业务资料')).attributes('disabled')).toBeDefined();
    expect(stale.findAll('button').some((button) => button.text().includes('新增仓库'))).toBe(false);
    stale.unmount();
  });

  it('serializes alias lines and the shared version on save', async () => {
    const wrapper = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text().includes('编辑业务资料')).trigger('click');
    const alias = wrapper.findAll('textarea').find((input) => input.attributes('placeholder')?.includes('用于展示和搜索'));
    await alias.setValue('OLD-4\nOLD-5');
    await wrapper.findAll('button').find((button) => button.text() === '保存').trigger('click');
    await flushPromises();
    expect(mocks.update).toHaveBeenCalledWith(4, expect.objectContaining({ expected_version: 3, legacy_codes: ['OLD-4', 'OLD-5'] }), expect.any(String));
    wrapper.unmount();
  });

  it('keeps component startup network failures handled and visible', async () => {
    mocks.options.mockRejectedValueOnce(new Error('options offline'));
    mocks.fetch.mockRejectedValueOnce(new Error('list offline'));
    const wrapper = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    expect(mocks.messageError).toHaveBeenCalledWith('options offline');
    expect(mocks.messageError).toHaveBeenCalledWith('list offline');
    wrapper.unmount();
  });

  it('reuses one idempotency key after a lost create response with the same payload', async () => {
    mocks.create.mockRejectedValueOnce(new Error('write response lost')).mockResolvedValueOnce({ success: true, data: rows[0] });
    const wrapper = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text().includes('新增仓库')).trigger('click');
    await wrapper.findAll('input')[1].setValue('new-us');
    await wrapper.findAll('input')[2].setValue('新仓');
    await wrapper.findAll('select')[2].setValue('US');
    const save = wrapper.findAll('button').find((button) => button.text() === '保存');
    await save.trigger('click');
    await flushPromises();
    expect(mocks.messageError).toHaveBeenCalledWith('write response lost');
    expect(wrapper.text()).toContain('新增仓库档案');
    await save.trigger('click');
    await flushPromises();
    expect(mocks.create).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls[0][1]).toBe(mocks.create.mock.calls[1][1]);
    wrapper.unmount();
  });

  it('blocks duplicate saves and dialog edits while a write is pending', async () => {
    let finishWrite;
    mocks.update.mockImplementationOnce(() => new Promise((resolve) => { finishWrite = resolve; }));
    const wrapper = mount(SupplyWarehouseArchiveV2, { global: { stubs, directives: { loading: () => {} } } });
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text().includes('编辑业务资料')).trigger('click');
    const save = wrapper.findAll('button').find((button) => button.text() === '保存');
    await save.trigger('click');
    await flushPromises();
    expect(save.attributes('disabled')).toBeDefined();
    expect(wrapper.findAll('button').find((button) => button.text() === '取消').attributes('disabled')).toBeDefined();
    await save.trigger('click');
    expect(mocks.update).toHaveBeenCalledTimes(1);
    finishWrite({ success: true, data: rows[0] });
    await flushPromises();
    wrapper.unmount();
  });

  it('allows callers to supply an idempotency key to the API adapter', async () => {
    const api = await vi.importActual('../src/api/supplyWarehousesV2');
    await api.createSupplyWarehouse({ code: 'new-us' }, 'same-write-key');
    await api.updateSupplyWarehouse(4, { expected_version: 3 }, 'same-write-key');
    expect(mocks.requestApi.mock.calls.map(([config]) => config.headers['Idempotency-Key'])).toEqual(['same-write-key', 'same-write-key']);
  });
});
