import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SampleImportDialog from './SampleImportDialog.vue';

const { requestApi } = vi.hoisted(() => ({ requestApi: vi.fn() }));
vi.mock('../../api/request', () => ({ requestApi }));

const dialogStub = {
  props: ['modelValue'],
  template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>'
};
const selectStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue', 'change'],
  methods: {
    select(event) {
      const value = event.target.value;
      const next = /^\d+$/.test(value) ? Number(value) : value;
      this.$emit('update:modelValue', next);
      this.$emit('change', next);
    }
  },
  template: '<select :value="modelValue ?? \'\'" :disabled="disabled" @change="select"><option value=""></option><slot/></select>'
};
const optionStub = {
  props: ['label', 'value', 'disabled'],
  template: '<option :value="value" :disabled="disabled">{{ label }}</option>'
};
const checkboxStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: '<label><input type="checkbox" :checked="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.checked)" /><slot/></label>'
};

function button(wrapper, label) {
  return wrapper.findAll('button').find(item => item.text() === label);
}

async function selectFile(wrapper, file = new File(['synthetic fixture'], 'orders.csv')) {
  const input = wrapper.get('input[type="file"]');
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] });
  await input.trigger('change');
}

const order = (orderNo, overrides = {}) => ({
  order_no: orderNo,
  preview_token: `fixture-token-${orderNo}`,
  big_seller_store: 'TEST-PH',
  country_code: 'PH',
  source_status: '待发货',
  warehouse_name: '测试仓库',
  sample_sent_at: '2026-11-01T13:12:00+08:00',
  shipped_at: null,
  row_numbers: [2],
  items: [{ requested_sku: 'SKU-TEST', quantity: 2 }],
  errors: [],
  ...overrides
});
const success = (data) => ({ success: true, code: 'OK', message: 'success', data });
const receipt = (results, replayed = false) => success({
  batch_id: 7,
  mode: 'partial',
  replayed,
  results: results.map((result, index) => ({ ...result, index })),
  created_count: results.filter(result => result.status === 'created').length
});
const candidate = (id) => ({ id, name: '同名达人', handle: `test${id}`, is_blacklisted: false });
const confirmCalls = () => requestApi.mock.calls.map(([call]) => call)
  .filter(call => call.url.endsWith('/sample-import/confirm/'));

async function openPreview(wrapper, orders) {
  requestApi.mockResolvedValueOnce(success({
    orders,
    order_count: orders.length,
    source_timezone: 'Asia/Shanghai',
    link_types: [{ value: 'YYJL', label: '运营建联' }]
  }));
  const file = new File(['synthetic fixture'], 'orders.csv');
  await selectFile(wrapper, file);
  await button(wrapper, '校验并预览').trigger('click');
  await flushPromises();
  expect(requestApi.mock.calls[0][0]).toMatchObject({ method: 'post', url: '/api/internal/influencers/sample-import/preview/' });
  expect(requestApi.mock.calls[0][0].data.get('file').name).toBe('orders.csv');
}

async function setCreator(row, candidates = []) {
  await row.get('input[aria-label="达人昵称"]').setValue('同名达人');
  requestApi.mockResolvedValueOnce(success({ candidates }));
  await button(row, '查找').trigger('click');
  await flushPromises();
  expect(requestApi.mock.lastCall[0]).toMatchObject({
    method: 'get', url: '/api/internal/influencers/resolve/', params: { q: '同名达人' }
  });
  await row.get('select[aria-label="送样类型"]').setValue('YYJL');
}

async function checkByLabel(wrapper, text) {
  const label = wrapper.findAll('label').find(item => item.text().includes(text));
  await label.get('input[type="checkbox"]').setValue(true);
}

describe('sample import dialog', () => {
  let wrapper;
  beforeEach(() => {
    requestApi.mockReset();
    wrapper = mount(SampleImportDialog, {
      props: { modelValue: true, canManage: true },
      global: { stubs: { ElDialog: dialogStub, ElSelect: selectStub, ElOption: optionStub, ElCheckbox: checkboxStub } }
    });
  });
  afterEach(() => wrapper.unmount());

  it('blocks non-CSV and oversized CSV without a request', async () => {
    await selectFile(wrapper, new File(['x'], 'orders.pdf'));
    expect(wrapper.text()).toContain('请选择 CSV 或 Excel');
    await selectFile(wrapper, new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'orders.csv'));
    expect(wrapper.text()).toContain('不能超过 2 MB');
    expect(button(wrapper, '校验并预览').element.disabled).toBe(true);
    expect(requestApi).not.toHaveBeenCalled();
  });

  it('displays all 13 order previews and expands only errors by default', async () => {
    const orders = Array.from({ length: 13 }, (_, index) => order(`TEST-ORDER-${index}`));
    orders[2].errors = [{ code: 'invalid_csv_row', row_number: 4, message: 'SKU 数量无效。' }];
    orders[3].preview_token = null;
    await openPreview(wrapper, orders);
    const rows = wrapper.findAll('.import-order');
    expect(rows).toHaveLength(13);
    expect(wrapper.text()).toContain('负责人：当前登录用户');
    expect(rows[0].get('details').element.open).toBe(false);
    expect(rows[2].get('details').element.open).toBe(true);
    expect(rows[2].text()).toContain('CSV 第 4 行：SKU 数量无效。');
    expect(rows[2].text()).toContain('测试仓库');
    expect(rows[2].get('.order-header input').element.disabled).toBe(true);
    expect(rows[3].text()).toContain('订单没有有效预览');
    expect(confirmCalls()).toHaveLength(0);
  });

  it('requires resolving ambiguous creators and acknowledging the CSV time zone', async () => {
    await openPreview(wrapper, [order('TEST-AMBIGUOUS')]);
    const row = wrapper.get('.import-order');
    await setCreator(row, [candidate(101), candidate(102)]);
    await row.get('.order-header input').setValue(true);
    expect(row.text()).toContain('请选择正确的达人档案');
    expect(row.text()).not.toContain('确认导入时创建待补全档案');
    expect(button(wrapper, '确认导入').element.disabled).toBe(true);
    await row.get('select[aria-label="达人档案"]').setValue('102');
    expect(button(wrapper, '确认导入').element.disabled).toBe(true);
    await checkByLabel(wrapper, '确认此文件的下单/发货时间为北京时间 UTC+8');
    expect(button(wrapper, '确认导入').element.disabled).toBe(false);
    expect(confirmCalls()).toHaveLength(0);
  });

  it('locks an uncertain submission and retries the exact selected batch', async () => {
    await openPreview(wrapper, [order('TEST-DRAFT'), order('TEST-UNCHECKED')]);
    const [row, unchecked] = wrapper.findAll('.import-order');
    await setCreator(unchecked, [candidate(101)]);
    await setCreator(row);
    await row.get('.order-header input').setValue(true);
    await checkByLabel(wrapper, '确认此文件的下单/发货时间为北京时间 UTC+8');
    expect(button(wrapper, '确认导入').element.disabled).toBe(true);
    await checkByLabel(row, '确认导入时创建待补全档案');

    let finish;
    requestApi.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await button(wrapper, '确认导入').trigger('click');
    await button(wrapper, '确认导入').trigger('click');
    expect(confirmCalls()).toHaveLength(1);
    const sent = confirmCalls()[0].data;
    expect(sent).toMatchObject({
      request_key: expect.any(String),
      source_timezone: 'Asia/Shanghai',
      timezone_confirmed: true,
      orders: [{ order_no: 'TEST-DRAFT', preview_token: 'fixture-token-TEST-DRAFT', nickname: '同名达人', link_type: 'YYJL' }]
    });
    expect(sent.orders[0]).not.toHaveProperty('owner');
    expect(sent.orders[0]).not.toHaveProperty('influencer_id');
    finish({ success: false, code: 'HTTP_NETWORK_ERROR', data: null });
    await flushPromises();
    expect(wrapper.text()).toContain('导入结果暂未确认');
    expect(wrapper.get('input[type="file"]').element.disabled).toBe(true);
    expect(wrapper.emitted('imported')).toBeUndefined();
    await button(wrapper, '暂时关闭').trigger('click');
    await wrapper.setProps({ modelValue: false });
    await wrapper.setProps({ modelValue: true });
    requestApi.mockResolvedValueOnce(success({}));
    await button(wrapper, '重试原请求').trigger('click');
    await flushPromises();
    expect(confirmCalls()[1].data).toEqual(sent);
    expect(wrapper.emitted('imported')).toBeUndefined();
    requestApi.mockResolvedValueOnce(receipt([{ order_no: 'TEST-DRAFT', status: 'created', fulfillment_id: 21 }], true));
    await button(wrapper, '重试原请求').trigger('click');
    await flushPromises();
    expect(confirmCalls()[2].data).toEqual(sent);
    expect(wrapper.emitted('imported')).toHaveLength(1);
  });

  it('refreshes only confirmed creations and requires a reason before retrying recent duplicates', async () => {
    const ids = ['TEST-CREATED', 'TEST-RECENT', 'TEST-CONFLICT'];
    await openPreview(wrapper, ids.map(id => order(id)));
    for (const row of wrapper.findAll('.import-order')) await setCreator(row, [candidate(101)]);
    await checkByLabel(wrapper, '确认此文件的下单/发货时间为北京时间 UTC+8');
    await button(wrapper, '勾选所有可导入订单').trigger('click');
    requestApi.mockResolvedValueOnce(receipt([
      { order_no: ids[0], status: 'created', fulfillment_id: 21 },
      { order_no: ids[1], status: 'needs_confirmation', code: 'recent_duplicate', message: '近 30 天已有同商品送样。' },
      { order_no: ids[2], status: 'conflict', code: 'order_conflict', message: '该订单号不可导入。' }
    ]));
    await button(wrapper, '确认导入').trigger('click');
    await flushPromises();
    const [created, recent, conflict] = wrapper.findAll('.import-order');
    expect(created.text()).toContain('已导入');
    expect(recent.text()).toContain('近 30 天已有同商品送样。');
    expect(conflict.text()).toContain('该订单号不可导入。');
    expect(conflict.get('.order-header input').element.disabled).toBe(true);
    expect(wrapper.emitted('imported')).toHaveLength(1);
    await checkByLabel(recent, '确认仍要导入本订单');
    expect(button(wrapper, '确认导入').element.disabled).toBe(true);
    await recent.get('input[aria-label="重复送样原因"]').setValue('  已核对，需要补寄  ');
    requestApi.mockResolvedValueOnce(receipt([{ order_no: ids[1], status: 'created', fulfillment_id: 22 }]));
    await button(wrapper, '确认导入').trigger('click');
    await flushPromises();
    expect(confirmCalls()[1].data.request_key).not.toBe(confirmCalls()[0].data.request_key);
    expect(confirmCalls()[1].data.orders).toEqual([{
      order_no: ids[1],
      preview_token: `fixture-token-${ids[1]}`,
      nickname: '同名达人',
      influencer_id: 101,
      link_type: 'YYJL',
      confirm_recent_duplicate: true,
      confirmation_reason: '已核对，需要补寄'
    }]);
    expect(wrapper.emitted('imported')).toHaveLength(2);
  });

  it('requires selecting an authorized candidate when confirmation finds a same-name match', async () => {
    await openPreview(wrapper, [order('TEST-NICKNAME-RACE')]);
    const row = wrapper.get('.import-order');
    await setCreator(row);
    await checkByLabel(row, '确认导入时创建待补全档案');
    await checkByLabel(wrapper, '确认此文件的下单/发货时间为北京时间 UTC+8');
    await row.get('.order-header input').setValue(true);
    requestApi.mockResolvedValueOnce(receipt([{
      order_no: 'TEST-NICKNAME-RACE',
      status: 'needs_influencer',
      code: 'ambiguous_influencer',
      message: '请从已授权候选中明确选择达人。',
      candidates: [{ id: 41, name: '同名达人', display_name: '同名达人' }]
    }]));
    await button(wrapper, '确认导入').trigger('click');
    await flushPromises();
    expect(row.text()).toContain('请从已授权候选中明确选择达人');
    expect(row.text()).not.toContain('确认导入时创建待补全档案');
    expect(button(wrapper, '确认导入').element.disabled).toBe(true);
    await row.get('select[aria-label="达人档案"]').setValue('41');
    expect(button(wrapper, '确认导入').element.disabled).toBe(false);
    expect(wrapper.emitted('imported')).toBeUndefined();
  });
});
