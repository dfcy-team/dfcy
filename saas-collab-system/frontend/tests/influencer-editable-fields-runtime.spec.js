import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const request = vi.hoisted(() => vi.fn());
const messages = vi.hoisted(() => ({ error: vi.fn(), warning: vi.fn(), success: vi.fn() }));
vi.mock('../src/api/request', () => ({ requestApi: request, requestWithMockFallback: request }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal(), ElMessage: messages, ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) }
}));

import OutreachTaskList from '../src/views/influencers/OutreachTaskList.vue';
import SampleFulfillmentList from '../src/views/influencers/SampleFulfillmentList.vue';

const stubs = {
  ElCard: { template: '<div><slot /></div>' },
  ElDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /><slot name="footer" /></section>' },
  ElDrawer: { template: '<div />' },
  ElTable: { template: '<div />' },
  ElPagination: { template: '<div />' },
  ElForm: { template: '<div><slot /></div>' },
  ElFormItem: { props: ['label'], template: '<div :data-label="label"><slot /></div>' },
  ElInput: {
    props: ['modelValue', 'readonly', 'disabled'], emits: ['update:modelValue'],
    template: '<input :value="modelValue" :readonly="readonly" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />'
  },
  ElSelect: {
    props: ['modelValue', 'disabled'], emits: ['update:modelValue'],
    template: '<select :disabled="disabled" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>'
  },
  ElOption: { props: ['value', 'label'], template: '<option :value="value">{{ label }}</option>' },
  ElInputNumber: { props: ['modelValue', 'disabled'], template: '<input type="number" :value="modelValue" :disabled="disabled" />' },
  ElAlert: { props: ['title'], template: '<p>{{ title }}</p>' },
  ElButton: { template: '<button><slot /></button>' }
};

const task = { id: 17, task_no: 'DRJL0279', task_name: 'Synthetic task', status: 'in_progress', store: 3, owners: [9], target_count: 20, version: 4 };
const sample = { id: 23, fulfillment_no: 'YPDD10987', type_no: 'DRJL0005', outreach_task_no: 'DRJL0266', outreach_task: 17, influencer: 7, store: 3, external_product_id: 'SYNTHETIC-PRODUCT', link_type: 'DRJL', status: 'shipped', version: 5, items: [] };
const render = (component) => mount(component, { global: { stubs } });
const writes = () => request.mock.calls.map(([config]) => config).filter((config) => config.method === 'patch');

beforeEach(() => {
  vi.clearAllMocks();
  request.mockImplementation(async (config) => {
    let data = { count: 0, results: [] };
    if (config.url.endsWith('/outreach-task-options/')) data = { stores: [{ id: 3, name: 'Synthetic store', country_code: 'PH' }], bd_users: [{ id: 9, username: 'synthetic' }] };
    if (config.url.endsWith('/sample-fulfillment-options/')) data = { warehouses: [] };
    if (config.method === 'patch') data = { ...(config.url.includes('/outreach-tasks/') ? task : sample), ...config.data };
    return { success: true, data };
  });
});

describe('editable task number and sample type', () => {
  it('combines creation dates with owner filtering, resets pagination and clears dates', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    Object.assign(wrapper.vm.filters, { createdFrom: '2026-08-01', createdTo: '2026-08-31', owner: 9 });
    wrapper.vm.page = 3;
    wrapper.vm.applyFilters();
    await flushPromises();
    const listCalls = () => request.mock.calls.map(([config]) => config).filter((config) => config.url.endsWith('/sample-fulfillments/'));
    expect(listCalls().at(-1).params).toMatchObject({ created_from: '2026-08-01', created_to: '2026-08-31', owner: 9, page: 1 });
    wrapper.vm.resetFilters();
    await flushPromises();
    expect(listCalls().at(-1).params).not.toHaveProperty('created_from');
    expect(listCalls().at(-1).params).not.toHaveProperty('created_to');
    wrapper.unmount();
  });

  it('does not request a reversed creation date range', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    request.mockClear();
    Object.assign(wrapper.vm.filters, { createdFrom: '2026-09-01', createdTo: '2026-08-31' });
    wrapper.vm.applyFilters();
    await flushPromises();
    expect(request).not.toHaveBeenCalled();
    expect(messages.warning).toHaveBeenCalledWith('结束日期不能早于开始日期');
    wrapper.unmount();
  });

  it('shows separate editable sample and type numbers and the read-only related task number', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    await flushPromises();
    expect(wrapper.get('[data-label="送样编号"] input').element.readOnly).toBe(false);
    expect(wrapper.get('[data-label="类型流水号"] input').element.value).toBe('DRJL0005');
    expect(wrapper.get('[data-label="关联建联任务编号"] input').element.value).toBe('DRJL0266');
    expect(wrapper.get('[data-label="关联建联任务编号"] input').element.readOnly).toBe(true);
    wrapper.unmount();
  });

  it('sends a number-only edit without resubmitting SKU costs or workflow facts', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    await wrapper.get('[data-label="送样编号"] input').setValue(' YPDD10646 ');
    await wrapper.get('[data-label="类型流水号"] input').setValue(' DRJL0008 ');
    await wrapper.vm.submit();
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({ data: { fulfillment_no: 'YPDD10646', type_no: 'DRJL0008' }, headers: { 'If-Match': '"5"' } });
    expect(Object.keys(writes()[0].data).sort()).toEqual(['fulfillment_no', 'type_no']);
    wrapper.unmount();
  });

  it.each(['送样编号', '类型流水号'])('requires a nonblank %s when editing', async (label) => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    await wrapper.get(`[data-label="${label}"] input`).setValue(' ');
    await wrapper.vm.submitEdit();
    expect(writes()).toEqual([]);
    expect(messages.warning).toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each([null, undefined, ''])('allows ordinary edits before legacy type number backfill (%s)', async (type_no) => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...sample, type_no });
    wrapper.vm.form.notes = 'Legacy note correction';
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(1);
    expect(writes()[0].data.notes).toBe('Legacy note correction');
    expect(writes()[0].data).not.toHaveProperty('type_no');
    expect(messages.warning).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('keeps legacy number-only corrections separate from cost and workflow edits', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...sample, type_no: null });
    await wrapper.get('[data-label="送样编号"] input').setValue('YPDD10646');
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(1);
    expect(writes()[0].data).toEqual({ fulfillment_no: 'YPDD10646' });
    wrapper.unmount();
  });

  it('retains the sample number draft on duplicate-number rejection', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    await wrapper.get('[data-label="送样编号"] input').setValue('YPDD10646');
    request.mockResolvedValueOnce({ success: false, http_status: 409, code: 'STATE_CONFLICT', message: '送样编号或类型流水号已被占用（含历史旧号），请使用其他编号。' });
    await wrapper.vm.submitEdit();
    expect(wrapper.vm.visible).toBe(true);
    expect(wrapper.vm.form.fulfillment_no).toBe('YPDD10646');
    expect(messages.success).not.toHaveBeenCalled();
    expect(messages.error).toHaveBeenCalledWith('送样编号或类型流水号已被占用（含历史旧号），请使用其他编号。');
    wrapper.unmount();
  });

  it('edits the task number and submits it with the existing ID and version', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openEdit(task);
    await flushPromises();
    const input = wrapper.get('[data-label="任务编号"] input');
    expect(input.element.readOnly).toBe(false);
    await input.setValue(' CORRECTED-279 ');
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({
      url: '/api/internal/influencers/outreach-tasks/17/',
      data: { task_no: 'CORRECTED-279' }, headers: { 'If-Match': '"4"' }
    });
    wrapper.unmount();
  });

  it.each(['completed', 'cancelled'])('only submits the number for a %s task', async (status) => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...task, status, owners: [], task_name: '' });
    await flushPromises();
    expect(wrapper.get('[data-label="任务名称"] input').element.disabled).toBe(true);
    expect(wrapper.get('[data-label="任务编号"] input').element.disabled).toBe(false);
    expect(wrapper.text()).not.toContain('已完成或已取消的任务仅支持修正任务编号');
    for (const label of ['任务优先级', '店铺', '任务状态', '负责人（BD）']) {
      expect(wrapper.get(`[data-label="${label}"] select`).element.disabled).toBe(true);
    }
    expect(wrapper.get('[data-label="目标人数"] input').element.disabled).toBe(true);
    await wrapper.get('[data-label="任务编号"] input').setValue('CORRECTED-TERMINAL');
    await wrapper.vm.submitEdit();
    expect(writes()[0].data).toEqual({ task_no: 'CORRECTED-TERMINAL' });
    wrapper.unmount();
  });

  it('rejects an empty task number before sending a request', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openEdit(task);
    await wrapper.get('[data-label="任务编号"] input').setValue('   ');
    await wrapper.vm.submitEdit();
    expect(messages.warning).toHaveBeenCalledWith('请填写任务编号');
    expect(writes()).toEqual([]);
    wrapper.unmount();
  });

  it('retains the draft after a duplicate-number response instead of reporting success', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openEdit(task);
    wrapper.vm.form.task_no = 'DUPLICATE';
    request.mockResolvedValueOnce({ success: false, http_status: 409, code: 'STATE_CONFLICT', message: '任务编号已被占用，请使用其他编号。' });
    await wrapper.vm.submitEdit();
    expect(wrapper.vm.createVisible).toBe(true);
    expect(wrapper.vm.form.task_no).toBe('DUPLICATE');
    expect(messages.error).toHaveBeenCalledWith('任务编号已被占用，请使用其他编号。');
    expect(messages.success).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('keeps task creation server-numbered', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openCreate();
    await flushPromises();
    expect(wrapper.get('[data-label="任务编号"] input').element.readOnly).toBe(true);
    Object.assign(wrapper.vm.form, { task_no: 'CLIENT-CANNOT-CHOOSE', task_name: 'New task', store: 3, owners: [9] });
    await wrapper.vm.submit();
    const created = request.mock.calls.map(([config]) => config).find((config) => config.method === 'post');
    expect(created.data).not.toHaveProperty('task_no');
    wrapper.unmount();
  });

  it('offers alternate types for linked samples and saves the selected type without identity fields', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    await flushPromises();
    const selector = wrapper.get('[data-label="送样类型"] select');
    expect(selector.element.disabled).toBe(false);
    expect(selector.findAll('option').map((option) => option.element.value)).toEqual(['DRJL', 'YYJL', 'PKDJ', 'ZBDR', 'TKOne']);
    await selector.setValue('YYJL');
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({ url: '/api/internal/influencers/sample-fulfillments/23/', data: { link_type: 'YYJL' } });
    for (const field of ['outreach_task', 'influencer', 'store', 'owner', 'fulfillment_no']) expect(writes()[0].data).not.toHaveProperty(field);
    wrapper.unmount();
  });

  it('offers the existing business types for an edited standalone sample', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...sample, outreach_task: null, link_type: 'YYJL' });
    await flushPromises();
    expect(Object.keys(wrapper.vm.selectableLinkTypes)).toEqual(['DRJL', 'YYJL', 'PKDJ', 'ZBDR', 'TKOne']);
    wrapper.unmount();
  });

  it('retains the legacy direct type while editing an existing direct sample', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...sample, outreach_task: null, link_type: 'direct' });
    await flushPromises();
    expect(wrapper.vm.selectableLinkTypes.direct).toBe('直接送样（历史）');
    wrapper.unmount();
  });
});
