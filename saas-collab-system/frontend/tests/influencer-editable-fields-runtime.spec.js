import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ElMessageBox } from 'element-plus';

const request = vi.hoisted(() => vi.fn());
const messages = vi.hoisted(() => ({ error: vi.fn(), warning: vi.fn(), success: vi.fn() }));
const permissions = vi.hoisted(() => ({ check: () => true }));
vi.mock('../src/api/request', () => ({ requestApi: request, requestWithMockFallback: request }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (code) => permissions.check(code), currentUser: {id:1,tenant_id:1}, authorizationStale:false }) }));
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
    props: { modelValue: {}, disabled: Boolean, multiple: Boolean }, emits: ['update:modelValue', 'change'],
    methods: { select(event) {
      const value = this.multiple ? Array.from(event.target.selectedOptions, option => option.value) : event.target.value;
      this.$emit('update:modelValue', value);
      this.$emit('change', value);
    } },
    template: '<select :disabled="disabled" :multiple="multiple" @change="select"><slot /></select>'
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
let serverSample;

beforeEach(() => {
  vi.clearAllMocks();
  permissions.check = () => true;
  serverSample = { ...sample };
  request.mockImplementation(async (config) => {
    let data = { count: 0, results: [] };
    if (config.method === 'get' && config.url.endsWith('/sample-fulfillments/23/')) data = serverSample;
    if (config.url.endsWith('/outreach-task-options/')) data = { stores: [{ id: 3, name: 'Synthetic store', country_code: 'PH' }], bd_users: [{ id: 9, username: 'synthetic' }] };
    if (config.url.endsWith('/sample-fulfillment-options/')) data = { warehouses: [], owners: [], stores: [] };
    if (config.method === 'patch') data = { ...(config.url.includes('/outreach-tasks/') ? task : sample), ...config.data };
    return { success: true, data };
  });
});

describe('editable task number and sample type', () => {
  it('distinguishes writer verification from historical links and renders completion time', () => {
    const wrapper=render(SampleFulfillmentList);
    const at='2026-11-28T02:30:00Z';
    expect(wrapper.vm.completionEvidenceLabel({kind:'linked',video_id:'V1',at})).toContain('来源未核验');
    expect(wrapper.vm.completionEvidenceLabel({kind:'linked',video_id:'V1',at})).not.toContain('系统核验');
    expect(wrapper.vm.completionEvidenceLabel({kind:'system',video_id:'V1',at})).toContain('系统核验');
    expect(wrapper.vm.completionEvidenceLabel({kind:'system',video_id:'V1',at})).toContain('10:30');
    expect(wrapper.vm.completionEvidenceLabel({kind:'manual',actor:'Actor',at})).toContain('Actor');
    wrapper.unmount();
  });

  it.each([[OutreachTaskList,'sampleVisible','sampleForm'],[SampleFulfillmentList,'visible','form']])('reads duplicate guidance only while the actual create-sample dialog is open', async (component, visibility, formName) => {
    const fallback=request.getMockImplementation();
    request.mockImplementation(config=>config.url.endsWith('/resolve/') && config.params?.duplicate_influencer
      ? Promise.resolve({success:true,data:{records:[{fulfillment_no:'EXISTING',status:'delivered'}]}}) : fallback(config));
    const wrapper=render(component);await flushPromises();
    wrapper.vm.influencerOptions=[{id:7,handle:'synthetic'}];wrapper.vm[formName].influencer=7;
    await flushPromises();
    const reads=()=>request.mock.calls.map(([c])=>c).filter(c=>c.params?.duplicate_influencer);
    expect(reads()).toHaveLength(0);
    wrapper.vm[visibility]=true;await flushPromises();
    expect(reads()).toHaveLength(1);expect(wrapper.vm.duplicateSampleWarning).toContain('EXISTING');
    wrapper.vm[visibility]=false;await flushPromises();expect(wrapper.vm.duplicateSampleWarning).toBe('');
    wrapper.unmount();
  });

  it('combines selected sample owners, resets owner, and batches only current-page eligible rows with versions', async () => {
    const fallback = request.getMockImplementation();
    request.mockImplementation(config => config.url.endsWith('/sample-fulfillment-options/')
      ? Promise.resolve({ success: true, data: { stores: [], owners: [{ id: 9, username: 'A' }, { id: 10, username: 'B' }] } })
      : fallback(config));
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    const latest = () => request.mock.calls.map(([config]) => config)
      .findLast(config => config.url.endsWith('/sample-fulfillments/')).params;
    const filter = wrapper.get('select[placeholder="全部送样负责人"]');
    await filter.setValue(['9', '10']);
    await flushPromises();
    expect(latest().owner).toBe('9,10');
    expect(latest().page_size).toBe(50);

    const overdue = { ...sample, id: 24, status: 'overdue', version: 6 };
    const cancelled = { ...sample, id: 25, status: 'cancelled', version: 7 };
    wrapper.vm.rows = [sample, overdue, cancelled];
    wrapper.vm.selectedSamples = [sample, overdue, cancelled, { ...sample, id: 90 }];
    await wrapper.vm.completeSelectedSamples();
    expect(writes().map(config => [config.url.split('/').at(-2), config.headers['If-Match']])).toEqual([['23', '"5"'], ['24', '"6"']]);
    expect(writes().every(config => config.data.status === 'completed' && config.data.confirm_terminal)).toBe(true);
    wrapper.unmount();
  });
  it('offers blacklist filtering and links the status-only action to the archive', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    await flushPromises();
    expect(wrapper.vm.editableStatusOptions.blacklisted).toBe('已拉黑');
    expect(wrapper.vm.FULFILLMENT_FILTER_STATUS_LABELS.blacklisted).toBe('已拉黑');
    expect(wrapper.get('.sku-header').text()).toContain('明细商品 ID');
    expect(wrapper.find('.sku-row select').exists()).toBe(true);
    const selector = wrapper.get('[data-label="状态"] select');
    expect(selector.findAll('option').some((option) => option.element.value === 'blacklisted')).toBe(true);
    wrapper.vm.form.status = 'blacklisted';
    wrapper.vm.form.notes = 'unsaved changes';
    wrapper.vm.items = [{ requested_sku: 'UNKNOWN', warehouse: null, quantity: 1 }];
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(1);
    expect(writes()[0].data).toEqual({ status: 'blacklisted', confirm_terminal: true });
    expect(messages.success).toHaveBeenCalledWith('送样及达人档案已同步拉黑');
    wrapper.unmount();
  });

  it('does not offer archive blacklisting without both manage permissions', async () => {
    permissions.check = (code) => code !== 'influencers.manage';
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    expect(wrapper.vm.editableStatusOptions.blacklisted).toBeUndefined();
    wrapper.unmount();
  });

  it('cancelling blacklist confirmation sends no write', async () => {
    const { ElMessageBox } = await import('element-plus');
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    wrapper.vm.form.status = 'blacklisted';
    ElMessageBox.confirm.mockRejectedValueOnce('cancel');
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(0);
    wrapper.unmount();
  });

  it('renders priority tasks as read-only rows and keeps recent requirements separate', async () => {
    const base = request.getMockImplementation();
    const recent = { ...task, dispatch_requirements: 'Demonstrate the product', status: 'paused',
      dispatch_time: '2026-11-17T08:30:00+08:00', priority: 'high' };
    const high = { id: 18, task_no: 'DRJL480480', task_name: '舒棉绒建联' };
    request.mockImplementation((config) => config.params?.recent_requirements
      ? Promise.resolve({ success: true, data: { results: [recent], priority_tasks: { urgent: [], high: [high] } } })
      : base(config));
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    const activity = wrapper.get('[aria-labelledby="activity-title"]');
    expect(activity.text()).toContain('Demonstrate the product');
    expect(activity.text()).toContain('已暂停');
    const priority = wrapper.get('.priority-task');
    expect(priority.text()).toBe('DRJL480480舒棉绒建联');
    expect(wrapper.get('[aria-labelledby="priority-title"]').findAll('button')).toHaveLength(0);
    await priority.trigger('click');
    await flushPromises();
    expect(request.mock.calls.map(([config]) => config.url)).not.toContain('/api/internal/influencers/outreach-tasks/18/');
    wrapper.unmount();
  });

  it('does not label an incomplete priority response as an empty task list', async () => {
    const base = request.getMockImplementation();
    request.mockImplementation((config) => config.params?.recent_requirements
      ? Promise.resolve({ success: true, data: { results: [] } })
      : base(config));
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    const priority = wrapper.get('[aria-labelledby="priority-title"]');
    expect(priority.text()).toContain('未能加载重点任务');
    expect(priority.text()).not.toContain('暂无紧急或高优先级任务');
    wrapper.unmount();
  });

  it('uses 50-row defaults and requests 200 rows from page one after a size change', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    expect(request.mock.calls.find(([config]) => config.url.endsWith('/outreach-tasks/') && config.params?.page_size)[0].params).toMatchObject({ page: 1, page_size: 50 });
    wrapper.vm.page = 4;
    wrapper.vm.pageSize = 200;
    wrapper.vm.filters.search = 'synthetic';
    wrapper.vm.onPageSizeChange();
    await flushPromises();
    expect(request.mock.calls.filter(([config]) => config.url.endsWith('/outreach-tasks/') && config.params?.page_size).at(-1)[0].params).toMatchObject({ page: 1, page_size: 200, search: 'synthetic' });
    wrapper.unmount();
    const samples = render(SampleFulfillmentList);
    await flushPromises();
    expect(request.mock.calls.find(([config]) => config.url.endsWith('/sample-fulfillments/') && config.params?.page_size)[0].params).toMatchObject({ page: 1, page_size: 50 });
    samples.vm.page = 3;
    samples.vm.pageSize = 200;
    samples.vm.filters.search = 'synthetic';
    samples.vm.onPageSizeChange();
    await flushPromises();
    expect(request.mock.calls.filter(([config]) => config.url.endsWith('/sample-fulfillments/') && config.params?.page_size).at(-1)[0].params).toMatchObject({ page: 1, page_size: 200, search: 'synthetic' });
    samples.unmount();
  });

  it('exposes copy only for managers and nondeleted rows', async () => {
    const source = await import('../src/views/influencers/OutreachTaskList.vue?raw');
    expect(source.default).toContain('v-if="TASK_REUSE_ENABLED && !row.is_deleted"');
    expect(source.default).toContain(':disabled="!canManage" @click.stop="openReuse(row)"');
    expect(source.default).toContain('const TASK_REUSE_ENABLED = true;');
  });
  it('reuses editable task details without copying task identity, state or progress', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    const source = { ...task, status: 'completed', priority: 'high', external_product_id: '1736417128860124444',
      sku_prefix: 'HY274', dispatch_requirements: 'Show the product in use', linked_count: 15, started_at: 'yesterday', finalized_at: 'today' };
    await wrapper.vm.openReuse(source);
    expect(wrapper.vm.createVisible).toBe(true);
    expect(wrapper.vm.editingTask).toBeNull();
    expect({ ...wrapper.vm.form }).toEqual({
      task_no: '', task_name: source.task_name, priority: 'normal', store: 3,
      external_product_id: source.external_product_id, sku_prefix: 'HY274',
      target_count: 1, dispatch_requirements: source.dispatch_requirements, owners: [9], status: 'pending', started_at: null, finalized_at: null
    });
    wrapper.vm.form.owners.push(10);
    expect(source.owners).toEqual([9]);
    expect(request.mock.calls.some(([config]) => config.method !== 'get')).toBe(false);
    wrapper.unmount();
  });

  it('filters all task pages by dispatcher without adding a status restriction', async () => {
    const base = request.getMockImplementation();
    request.mockImplementation(async (config) => {
      if (config.url.endsWith('/outreach-task-options/')) {
        return { success: true, data: { dispatchers: [{ id: 55, name: 'Synthetic dispatcher' }] } };
      }
      if (config.url.endsWith('/outreach-tasks/')) {
        const data = config.params.dispatcher
          ? { count: 110, results: [{ ...task, id: config.params.page, status: 'completed' }] }
          : { count: 200, results: [{ ...task, dispatcher_id: 1 }] };
        return { success: true, data };
      }
      return base(config);
    });
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    expect(wrapper.vm.dispatcherOptions).toEqual([{ id: 55, name: 'Synthetic dispatcher' }]);
    wrapper.vm.page = 3;
    wrapper.vm.filters.dispatcher = 55;
    wrapper.vm.applyFilters();
    await flushPromises();
    expect(request.mock.lastCall[0].params).toMatchObject({ page: 1, dispatcher: 55 });
    expect(request.mock.lastCall[0].params).not.toHaveProperty('status');
    expect(wrapper.vm.total).toBe(110);
    expect(wrapper.vm.rows[0].status).toBe('completed');
    wrapper.vm.page = 2;
    wrapper.vm.filters.normalOnly = true;
    await wrapper.vm.load();
    expect(request.mock.lastCall[0].params).toMatchObject({ page: 2, dispatcher: 55, normal_only: 'true' });
    wrapper.unmount();
  });

  it('warns about linked samples and reports the server cascade count', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    request.mockResolvedValue({ success: true, data: { deleted_sample_count: 2 } });
    await wrapper.vm.removeTask({ ...task });
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('全部关联送样记录'), '确认删除任务及关联送样', { type: 'warning' });
    expect(request.mock.calls.some(([config]) => config.method === 'delete' && config.url.endsWith('/outreach-tasks/17/'))).toBe(true);
    expect(messages.success).toHaveBeenCalledWith('任务及 2 条关联送样已删除');
    wrapper.unmount();
  });

  it('does not send a delete request when the cascade warning is cancelled', async () => {
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    ElMessageBox.confirm.mockRejectedValueOnce(new Error('cancel'));
    await wrapper.vm.removeTask({ ...task });
    expect(request.mock.calls.some(([config]) => config.method === 'delete')).toBe(false);
    expect(messages.success).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('loads the stored Beijing time and sends a time-only patch without SKU changes', async () => {
    serverSample = { ...sample, sample_sent_at: '2026-11-18T15:04:06Z' };
    const wrapper = render(SampleFulfillmentList);
    try {
      await flushPromises();
      await wrapper.vm.openEdit(sample);
      expect(wrapper.vm.form.sample_sent_at).toBe('2026-11-18T23:04:06');
      await wrapper.get('input[type="datetime-local"]').setValue('2026-11-17T22:03:02');
      await wrapper.vm.submitEdit();
      expect(writes()).toHaveLength(1);
      expect(writes()[0].data).toEqual({ sample_sent_at: '2026-11-17T22:03:02+08:00' });
    } finally {
      wrapper.unmount();
    }
  });

  it('filters by a permitted store absent from the current fulfillment page', async () => {
    request.mockImplementation(async (config) => ({
      success: true,
      data: config.url.endsWith('/sample-fulfillment-options/')
        ? { owners: [], stores: [{ id: 3, name: 'Page one shop' }, { id: 9, name: 'Other shop' }] }
        : { count: 21, results: [config.params.store
          ? { ...sample, store: 9, store_name: 'Other shop' }
          : { ...sample, store_name: 'Page one shop' }] }
    }));
    const wrapper = render(SampleFulfillmentList);
    try {
      await flushPromises();
      const storeFilter = wrapper.get('.toolbar select[placeholder="全部店铺"]');
      expect(storeFilter.findAll('option').map((option) => option.text())).toEqual(['Page one shop', 'Other shop']);
      await storeFilter.setValue(['3', '9']);
      await wrapper.get('.toolbar select[placeholder="全部状态"]').setValue(['shipped', 'completed']);
      await wrapper.findAll('.toolbar button').find((button) => button.text() === '查询').trigger('click');
      await flushPromises();
      expect(request.mock.calls.at(-1)[0].params).toMatchObject({ page: 1, store: '3,9', status: 'shipped,completed' });
      expect(storeFilter.findAll('option').map((option) => option.text())).toEqual(['Page one shop', 'Other shop']);
      expect(request.mock.calls.filter(([config]) => config.params?.filters_only === 'true')).toHaveLength(1);
    } finally {
      wrapper.unmount();
    }
  });

  it.each(['task', 'standalone'])('passes the selected store for country-scoped nickname creation (%s)', async (kind) => {
    const wrapper = render(kind === 'task' ? OutreachTaskList : SampleFulfillmentList);
    await flushPromises();
    request.mockResolvedValue({ success: true, data: { id: 907, name: 'Country creator', created: true } });
    if (kind === 'task') {
      wrapper.vm.sampleForm.store = 3;
      wrapper.vm.sampleForm.influencer = 'Country creator';
      await wrapper.vm.resolveSelectedSampleInfluencer();
    } else {
      wrapper.vm.form.store = 3;
      await wrapper.vm.resolveSelectedInfluencer('Country creator');
    }
    const call = request.mock.calls.map(([config]) => config).find((config) => config.method === 'post' && config.url.endsWith('/resolve/'));
    expect(call.data).toMatchObject({ nickname: 'Country creator', store_id: 3 });
    wrapper.unmount();
  });

  it('finds the unique authorized store from product ID without selecting a store first', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    request.mockResolvedValue({ success: true, data: {
      candidates: [{ store_id: 23, store_name: 'TK1PH', country_code: 'PH' }], unique: true,
      store: { id: 23, country_code: 'PH', site_code: 'not-a-country' },
      product: { product_name: 'Matched', skus: ['SKU-A'] },
      warehouses: [{ id: 81, country_code: 'PH' }]
    } });
    wrapper.vm.form.external_product_id = 'PRODUCT';
    await wrapper.vm.lookupProductById();
    await flushPromises();
    expect(request.mock.calls.at(-1)[0].params).toEqual({ product_id: 'PRODUCT' });
    expect(wrapper.vm.form.store).toBe(23);
    expect(wrapper.vm.form.product_name_snapshot).toBe('Matched');
    expect(wrapper.vm.items[0]).toMatchObject({ site_code: 'PH', requested_sku: 'SKU-A', warehouse: 81 });
    wrapper.vm.visible = true;
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.productStoreLocked).toBe(true);
    expect(wrapper.find('[data-label="店铺"] select').exists()).toBe(false);
    expect(wrapper.find('[data-label="店铺"] input').attributes('readonly')).toBeDefined();
    expect(wrapper.find('[data-label="国家"] input').attributes('readonly')).toBeDefined();
    expect(wrapper.find('[data-label="产品 ID"] input').attributes('readonly')).toBeUndefined();
    wrapper.vm.form.external_product_id = 'OTHER-PRODUCT';
    expect(wrapper.vm.productStoreLocked).toBe(false);
    wrapper.unmount();
  });

  it('looks up product ID after typing without requiring blur', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    request.mockResolvedValue({ success: true, data: { candidates: [{ store_id: 23, store_name: 'PH', country_code: 'PH' }], unique: true,
      store: { id: 23, country_code: 'PH' }, product: { product_name: 'Automatic', skus: [] }, warehouses: [] } });
    wrapper.vm.visible = true;
    await wrapper.vm.$nextTick();
    await wrapper.find('[data-label="产品 ID"] input').setValue('PRODUCT');
    await new Promise((resolve) => setTimeout(resolve, 400));
    await flushPromises();
    expect(wrapper.vm.form.store).toBe(23);
    expect(wrapper.find('[data-label="国家"]').exists()).toBe(true);
    expect(wrapper.find('[data-label="国家 / 站点"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('blocks saving when product matching fails instead of using an obsolete store silently', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    Object.assign(wrapper.vm.form, { store: 3, influencer: 7, external_product_id: 'NEW' });
    request.mockResolvedValue({ success: false, message: 'Unavailable' });
    await wrapper.vm.lookupProductById();
    request.mockClear();
    await wrapper.vm.submit();
    expect(messages.warning).toHaveBeenCalledWith('商品匹配失败，请重试或重新选择店铺后保存');
    expect(request).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('requires manual store choice for multiple matches and then loads its country', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    const candidates = [
      { store_id: 3, store_name: 'PH store', country_code: 'PH' },
      { store_id: 24, store_name: 'MY store', country_code: 'MY' }
    ];
    request.mockResolvedValueOnce({ success: true, data: { candidates, unique: false, warehouses: [] } });
    Object.assign(wrapper.vm.form, { store: 3, external_product_id: 'PRODUCT' });
    await wrapper.vm.lookupProductById();
    expect(wrapper.vm.form.store).toBeNull();
    expect(wrapper.vm.productStoreOptions.map((row) => row.id)).toEqual([3, 24]);
    expect(wrapper.vm.productLookupHint).toContain('多个店铺');
    expect(wrapper.vm.productStoreLocked).toBeFalsy();
    request.mockResolvedValueOnce({ success: true, data: { store: { id: 24, country_code: 'MY' },
      product: { product_name: 'MY product', skus: ['MY-SKU'] }, warehouses: [{ id: 82, country_code: 'MY' }] } });
    wrapper.vm.form.store = 24;
    await wrapper.vm.selectProductStore();
    await flushPromises();
    expect(wrapper.vm.items[0]).toMatchObject({ site_code: 'MY', warehouse: 82 });
    expect(wrapper.vm.productStoreLocked).toBe(true);
    wrapper.unmount();
  });

  it('clears obsolete automatic store on no match and keeps manual store selection available', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    Object.assign(wrapper.vm.form, { store: 3, external_product_id: 'UNKNOWN' });
    wrapper.vm.autoMatchedStore = 3;
    wrapper.vm.storeOptions = [{ id: 3, name: 'Manual store', country_code: 'PH' }];
    request.mockResolvedValue({ success: true, data: { candidates: [], unique: false, warehouses: [] } });
    await wrapper.vm.lookupProductById();
    expect(wrapper.vm.form.store).toBeNull();
    expect(wrapper.vm.productLookupHint).toContain('未在授权店铺');
    expect(wrapper.vm.productStoreOptions).toHaveLength(1);
    wrapper.unmount();
  });

  it('inherits country separately from platform site and submits multiple SKU rows', async () => {
    const fallback = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: true, data: {
        store: { id: 3, country_code: 'MY', site_code: 'tiktok-my' },
        warehouses: [{ id: 81, name: 'MY warehouse', country_code: 'MY' }],
        product: { product_name: 'Matched product', skus: ['SKU-A', 'SKU-B'] }
      } } : fallback(config));
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openSampleCreate({ ...task, external_product_id: 'PRODUCT' }, { id: 5, influencer: 7 });
    expect(wrapper.vm.sampleCountry).toBe('MY');
    expect(wrapper.find('[data-label="国家"]').text()).not.toContain('tiktok-my');
    expect(wrapper.vm.sampleForm.site_code).toBe('MY');
    expect(wrapper.vm.sampleForm.requested_sku).toBe('');
    wrapper.vm.sampleForm.requested_sku = 'SKU-A';
    wrapper.vm.addSampleItem();
    wrapper.vm.sampleExtraItems[0].requested_sku = 'SKU-B';
    wrapper.vm.sampleExtraItems[0].quantity = 2;
    await wrapper.vm.submitSample();
    const post = request.mock.calls.map(([c]) => c).find((c) => c.method === 'post' && c.url.endsWith('/sample-fulfillments/'));
    expect(post.data.items).toEqual([
      { site_code: 'MY', requested_sku: 'SKU-A', warehouse: 81, quantity: 1, external_product_id: 'PRODUCT' },
      { site_code: 'MY', requested_sku: 'SKU-B', warehouse: 81, quantity: 2, external_product_id: 'PRODUCT' }
    ]);
    wrapper.unmount();
  });

  it('fills new fulfillment SKU and country, but preserves historical rows', async () => {
    const fallback = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: true, data: { store: { id: 3, country_code: 'MY', site_code: '' },
        product: { product_name: 'Matched', skus: ['SKU-A'] }, warehouses: [{ id: 81, country_code: 'MY' }] } }
      : fallback(config));
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    wrapper.vm.storeOptions = [{ id: 3, country_code: 'MY' }];
    Object.assign(wrapper.vm.form, { store: 3, external_product_id: 'PRODUCT' });
    await wrapper.vm.refreshProductContext(true);
    await flushPromises();
    expect(wrapper.vm.items[0]).toMatchObject({ site_code: 'MY', requested_sku: 'SKU-A', warehouse: 81 });
    expect(wrapper.vm.form.product_name_snapshot).toBe('Matched');
    wrapper.vm.editingSample = sample;
    wrapper.vm.items = [{ site_code: 'OLD', requested_sku: 'HISTORICAL', warehouse: null, quantity: 3 }];
    await wrapper.vm.refreshProductContext(false);
    expect(wrapper.vm.items[0]).toEqual({ site_code: 'OLD', requested_sku: 'HISTORICAL', warehouse: null, quantity: 3 });
    await wrapper.vm.addSkuItem();
    expect(wrapper.vm.items[1]).toMatchObject({ site_code: 'MY', warehouse: 81, quantity: 1 });
    wrapper.unmount();
  });

  it('ignores stale product lookup responses after the product changes', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    let finishOld;
    request.mockImplementation((config) => config.params?.product_id === 'OLD'
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve({ success: true, data: { store: { id: 3, country_code: 'MY' }, product: { product_name: 'New', skus: ['NEW'] }, warehouses: [] } }));
    Object.assign(wrapper.vm.form, { store: 3, external_product_id: 'OLD' });
    const pending = wrapper.vm.refreshProductContext(true);
    wrapper.vm.form.external_product_id = 'NEW';
    await wrapper.vm.refreshProductContext(true);
    finishOld({ success: true, data: { store: { id: 3, country_code: 'PH' }, product: { product_name: 'Old', skus: ['OLD'] } } });
    await pending;
    expect(wrapper.vm.form.product_name_snapshot).toBe('New');
    expect(wrapper.vm.productSkuOptions).toEqual(['NEW']);
    wrapper.unmount();
  });

  it('replaces only auto-filled SKU on product changes and keeps chosen warehouses on refresh', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    wrapper.vm.storeOptions = [{ id: 3, country_code: 'MY' }];
    request.mockImplementation(async (config) => ({ success: true, data: {
      store: { id: 3, country_code: 'MY' },
      product: { product_name: config.params.product_id, skus: [config.params.product_id] },
      warehouses: [{ id: 81, country_code: 'MY' }, { id: 82, country_code: 'MY' }]
    } }));
    Object.assign(wrapper.vm.form, { store: 3, external_product_id: 'OLD' });
    await wrapper.vm.refreshProductContext(true);
    await flushPromises();
    expect(wrapper.vm.items[0].warehouse).toBeNull();
    wrapper.vm.items[0].warehouse = 82;
    wrapper.vm.form.external_product_id = 'NEW';
    await wrapper.vm.refreshProductContext(true);
    await flushPromises();
    expect(wrapper.vm.items[0]).toMatchObject({ requested_sku: 'NEW', warehouse: 82 });
    wrapper.vm.items[0].requested_sku = 'MANUAL';
    await wrapper.vm.refreshProductContext(true);
    expect(wrapper.vm.items[0].requested_sku).toBe('MANUAL');
    wrapper.unmount();
  });

  it('blocks opening when warehouse loading fails and clears stale options', async () => {
    const fallback = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: false, message: 'Unavailable' } : fallback(config));
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openSampleCreate(task, { id: 5, influencer: 7 });
    expect(wrapper.vm.sampleVisible).toBe(false);
    expect(wrapper.vm.sampleWarehouses).toEqual([]);
    expect(messages.error).toHaveBeenCalled();
    wrapper.unmount();
  });

  it('defaults a sole warehouse in new fulfillment rows but preserves edit rows', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    wrapper.vm.storeOptions = [{ id: 3, country_code: 'PH' }];
    wrapper.vm.warehouseOptions = [{ id: 81, country_code: 'PH' }];
    wrapper.vm.form.store = 3;
    await flushPromises();
    expect(wrapper.vm.items[0].warehouse).toBe(81);
    wrapper.vm.editingSample = sample;
    wrapper.vm.items = [{ requested_sku: 'OLD', warehouse: null, quantity: 1 }];
    wrapper.vm.warehouseOptions = [{ id: 82, country_code: 'PH' }];
    await flushPromises();
    expect(wrapper.vm.items[0].warehouse).toBeNull();
    wrapper.unmount();
  });

  it('auto-selects the only same-country warehouse and submits its ID', async () => {
    permissions.check = (code) => code !== 'influencers.fulfillment.view';
    const fallback = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: true, data: { warehouses: [{ id: 81, name: 'PH', country_code: 'PH' }, { id: 82, name: 'TH', country_code: 'TH' }] } }
      : fallback(config));
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openSampleCreate(task, { id: 5, influencer: 7 });
    expect(wrapper.vm.sampleVisible).toBe(true);
    expect(request.mock.calls.some(([c]) => c.url.endsWith('/sample-fulfillment-options/'))).toBe(false);
    expect(wrapper.vm.sampleForm.warehouse).toBe(81);
    expect(wrapper.vm.sampleWarehouses.map((w) => w.id)).toEqual([81]);
    wrapper.vm.sampleForm.requested_sku = 'DEMO-SKU';
    await wrapper.vm.submitSample();
    const post = request.mock.calls.map(([c]) => c).find((c) => c.method === 'post' && c.url.endsWith('/sample-fulfillments/'));
    expect(post.data.items[0]).toMatchObject({ requested_sku: 'DEMO-SKU', warehouse: 81 });
    expect(post.data.items[0]).not.toHaveProperty('unit_cost');
    wrapper.unmount();
  });

  it('does not default multiple warehouses or submit without an allowed selection', async () => {
    const fallback = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: true, data: { warehouses: [{ id: 81, country_code: 'PH' }, { id: 82, country_code: 'PH' }] } }
      : fallback(config));
    const wrapper = render(OutreachTaskList);
    await flushPromises();
    await wrapper.vm.openSampleCreate(task, { id: 5, influencer: 7 });
    expect(wrapper.vm.sampleForm.warehouse).toBeNull();
    request.mockClear();
    await wrapper.vm.submitSample();
    expect(messages.warning).toHaveBeenCalledWith('请选择该SKU的发货仓库');
    wrapper.vm.sampleForm.warehouse = 999;
    await wrapper.vm.submitSample();
    expect(request).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('uses fresh detail and version instead of the stale list row', async () => {
    serverSample = { ...sample, version: 8, notes: 'Updated by another user' };
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    expect(wrapper.vm.form.notes).toBe(serverSample.notes);
    wrapper.vm.form.fulfillment_no = 'YPDD10646';
    await wrapper.vm.submitEdit();
    expect(writes()[0].headers['If-Match']).toBe('"8"');
    expect(writes()[0].data).toEqual({ fulfillment_no: 'YPDD10646' });
    wrapper.unmount();
  });

  it('does not open a stale editor when fresh detail is unavailable', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    request.mockResolvedValueOnce({ success: false, message: '详情读取失败' });
    await wrapper.vm.openEdit(sample);
    expect(wrapper.vm.visible).toBe(false);
    expect(writes()).toEqual([]);
    expect(messages.error).toHaveBeenCalledWith('详情读取失败');
    wrapper.unmount();
  });

  it('inherits the bound store country when adding the first SKU to a legacy sample', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    expect(wrapper.vm.items[0].site_code).toBe('PH');
    expect(serverSample.items).toEqual([]);
    wrapper.unmount();
  });

  it('keeps SKU items inside the fresh detail object', async () => {
    serverSample = { ...sample, version: 9, items: [{ id: 901, requested_sku: 'SKU-A', quantity: 2 }] };
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openDetail(sample);
    expect(wrapper.vm.detailSample.id).toBe(sample.id);
    expect(wrapper.vm.detailSample.version).toBe(9);
    expect(wrapper.vm.detailSample.items).toEqual(serverSample.items);
    await wrapper.vm.openEdit(sample);
    expect(wrapper.vm.editingSample.id).toBe(sample.id);
    expect(wrapper.vm.items).toEqual(serverSample.items);
    wrapper.unmount();
  });

  it.each([false, true])('edits multiple item products without changing the task product (linked: %s)', async (linked) => {
    serverSample = { ...sample, outreach_task: linked ? sample.outreach_task : null,
      external_product_id: linked ? 'PRODUCT-A' : 'PRODUCT-A,PRODUCT-B' };
    const baseRequest = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: true, data: { store: { id: 3, country_code: 'PH' },
        warehouses: [{ id: 81, country_code: 'PH' }],
        product: config.params.product_id === 'PRODUCT-B' ? { skus: ['SKU-B'] } : null } }
      : baseRequest(config));
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    expect(wrapper.vm.formProductIds).toEqual(linked ? ['PRODUCT-A'] : ['PRODUCT-A', 'PRODUCT-B']);
    expect(wrapper.get('[data-label="产品 ID"] input').element.readOnly).toBe(true);
    expect(wrapper.text()).toContain('明细商品 ID');
    expect(wrapper.vm.items[0].external_product_id).toBe('');
    await wrapper.vm.addSkuItem();
    Object.assign(wrapper.vm.items[0], { external_product_id: 'PRODUCT-A', requested_sku: 'SKU-A', warehouse: 81 });
    Object.assign(wrapper.vm.items[1], { external_product_id: 'PRODUCT-B', requested_sku: 'SKU-B' });
    await wrapper.vm.loadItemProduct(wrapper.vm.items[1]);
    expect(wrapper.vm.itemSkuOptions(wrapper.vm.items[1])).toEqual(['SKU-B']);
    await wrapper.vm.submitEdit();
    expect(writes()[0].data.items.map(({ external_product_id, requested_sku }) => [external_product_id, requested_sku]))
      .toEqual([['PRODUCT-A', 'SKU-A'], ['PRODUCT-B', 'SKU-B']]);
    expect(writes()[0].data).not.toHaveProperty('external_product_id');
    expect(writes()[0].data).not.toHaveProperty('outreach_task');
    wrapper.unmount();
  });

  it('allows filling a missing product on a standalone sample without resubmitting SKU lines', async () => {
    serverSample = { ...sample, outreach_task: null, external_product_id: '' };
    const baseRequest = request.getMockImplementation();
    request.mockImplementation(async (config) => config.url.endsWith('/sample-warehouse-options/')
      ? { success: true, data: { store: { id: 3, country_code: 'PH' },
        product: config.params.product_id === 'VERIFIED' ? { skus: ['SKU'] } : null } }
      : baseRequest(config));
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    const input = wrapper.get('[data-label="产品 ID"] input');
    expect(input.element.readOnly).toBe(false);
    await input.setValue('WRONG');
    await wrapper.vm.submitEdit();
    expect(writes()).toHaveLength(0);
    await input.setValue('VERIFIED');
    await wrapper.vm.submitEdit();
    expect(writes()[0].data).toEqual({ external_product_id: 'VERIFIED' });
    expect(request.mock.calls.some(([c]) => c.params?.store === 3 && c.params?.product_id === 'VERIFIED')).toBe(true);
    wrapper.unmount();
  });

  it('ignores an edit response after the draft is discarded', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    let resolveDetail;
    request.mockImplementationOnce(() => new Promise((resolve) => { resolveDetail = resolve; }));
    const pending = wrapper.vm.openEdit(sample);
    wrapper.vm.discardDraft();
    resolveDetail({ success: true, data: sample });
    await pending;
    expect(wrapper.vm.visible).toBe(false);
    wrapper.unmount();
  });

  it('preserves the draft and version without retrying after a concurrent change', async () => {
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit(sample);
    wrapper.vm.form.notes = 'Unsaved draft';
    request.mockResolvedValueOnce({ success: false, http_status: 409, code: 'STATE_CONFLICT', data: { version: ['Fulfillment was changed by another request.'] } });
    await wrapper.vm.submitEdit();
    expect(wrapper.vm.visible).toBe(true);
    expect(wrapper.vm.form.notes).toBe('Unsaved draft');
    expect(wrapper.vm.editingSample.version).toBe(5);
    expect(writes()).toHaveLength(1);
    expect(messages.error).toHaveBeenCalledWith(expect.stringContaining('本次修改未保存'));
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
    serverSample = { ...sample, type_no };
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
    serverSample = { ...sample, type_no: null };
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
      expect(wrapper.get(`[data-label="${label}"] select`).element.disabled).toBe(!(status === 'completed' && label === '任务状态'));
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
    serverSample = { ...sample, outreach_task: null, link_type: 'YYJL' };
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...sample, outreach_task: null, link_type: 'YYJL' });
    await flushPromises();
    expect(Object.keys(wrapper.vm.selectableLinkTypes)).toEqual(['DRJL', 'YYJL', 'PKDJ', 'ZBDR', 'TKOne']);
    wrapper.unmount();
  });

  it('retains the legacy direct type while editing an existing direct sample', async () => {
    serverSample = { ...sample, outreach_task: null, link_type: 'direct' };
    const wrapper = render(SampleFulfillmentList);
    await flushPromises();
    await wrapper.vm.openEdit({ ...sample, outreach_task: null, link_type: 'direct' });
    await flushPromises();
    expect(wrapper.vm.selectableLinkTypes.direct).toBe('直接送样（历史）');
    wrapper.unmount();
  });
});
