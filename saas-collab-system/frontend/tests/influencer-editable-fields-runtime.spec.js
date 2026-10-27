import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const request = vi.hoisted(() => vi.fn());
const messages = vi.hoisted(() => ({ error: vi.fn(), warning: vi.fn(), success: vi.fn() }));
const permissions = vi.hoisted(() => ({ check: () => true }));
vi.mock('../src/api/request', () => ({ requestApi: request, requestWithMockFallback: request }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (code) => permissions.check(code) }) }));
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
let serverSample;

beforeEach(() => {
  vi.clearAllMocks();
  permissions.check = () => true;
  serverSample = { ...sample };
  request.mockImplementation(async (config) => {
    let data = { count: 0, results: [] };
    if (config.method === 'get' && config.url.endsWith('/sample-fulfillments/23/')) data = serverSample;
    if (config.url.endsWith('/outreach-task-options/')) data = { stores: [{ id: 3, name: 'Synthetic store', country_code: 'PH' }], bd_users: [{ id: 9, username: 'synthetic' }] };
    if (config.url.endsWith('/sample-fulfillment-options/')) data = { warehouses: [] };
    if (config.method === 'patch') data = { ...(config.url.includes('/outreach-tasks/') ? task : sample), ...config.data };
    return { success: true, data };
  });
});

describe('editable task number and sample type', () => {
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
