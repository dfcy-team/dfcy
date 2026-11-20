import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import Operations from '../src/components/BestWarehouseOperations.vue';
const api = vi.hoisted(() => ({ requestApi: vi.fn() }));
vi.mock('../src/api/request', () => api);
const operations = [
  { name: 'QUERY', label: '库存查询', module: '库存', write: false, fields: [], template: { customerCode: 'EXAMPLE', warehouseCode: 'EXAMPLE' } },
  { name: 'CREATE', label: '创建单据', module: '订单', write: true, fields: [], template: { orderNumber: 'TEST-ORDER' } },
];
const stubs = {
  ElAlert: { props: ['title'], template: '<div role="alert">{{ title }}</div>' },
  ElInput: { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<textarea :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' },
};
beforeEach(() => { api.requestApi.mockReset(); });
async function open({ write = false, execution = true, canManage = true } = {}) {
  api.requestApi.mockResolvedValueOnce({ success: true, data: { operations, callbacks: [{ name: 'FEEDBACK', label: '订单反馈' }], write_enabled: write, execution_enabled: execution } });
  const wrapper = mount(Operations, { props: { authorizationId: 17, customerCode: 'TEST-C', warehouseCode: 'TEST-W', canRead: true, canManage }, global: { stubs } });
  await flushPromises();
  return wrapper;
}
function button(wrapper, text) { return wrapper.findAll('button').find(item => item.text() === text); }
it('scopes the request template and only executes on explicit click', async () => {
  const wrapper = await open();
  await wrapper.find('select').setValue('QUERY');
  expect(JSON.parse(wrapper.find('textarea').element.value)).toEqual({ customerCode: 'TEST-C', warehouseCode: 'TEST-W' });
  expect(api.requestApi).toHaveBeenCalledTimes(1);
  api.requestApi.mockResolvedValueOnce({ success: true, data: { local_business_updated: false } });
  await button(wrapper, '执行只读查询').trigger('click'); await flushPromises();
  expect(api.requestApi.mock.calls.at(-1)[0]).toMatchObject({ noMockFallback: true, url: '/api/internal/integrations/warehouse-authorizations/17/operations/', data: { provider: 'best_ecapi', operation: 'QUERY' } });
  wrapper.unmount();
});
it.each([{ write: false }, { write: true, canManage: false }])('blocks a write without server capability or permission: %j', async options => {
  const wrapper = await open(options);
  await wrapper.find('select').setValue('CREATE');
  expect(button(wrapper, '确认执行写入').attributes('disabled')).toBeDefined();
  expect(wrapper.find('input[type="checkbox"]').attributes('disabled')).toBeDefined();
  expect(api.requestApi).toHaveBeenCalledTimes(1);
  wrapper.unmount();
});
it('keeps the write idempotency key after an uncertain response', async () => {
  const wrapper = await open({ write: true });
  await wrapper.find('select').setValue('CREATE');
  expect(button(wrapper, '确认执行写入').attributes('disabled')).toBeDefined();
  await wrapper.find('input[type="checkbox"]').setValue(true);
  api.requestApi.mockRejectedValue(new Error('结果未确认'));
  await button(wrapper, '确认执行写入').trigger('click'); await flushPromises();
  const first = api.requestApi.mock.calls.at(-1)[0].data;
  await button(wrapper, '确认执行写入').trigger('click'); await flushPromises();
  expect(api.requestApi.mock.calls.at(-1)[0].data.idempotency_key).toBe(first.idempotency_key);
  expect(wrapper.text()).toContain('结果未确认');
  wrapper.unmount();
});
it('shows stored callbacks without treating them as posted business results', async () => {
  const wrapper = await open();
  api.requestApi.mockResolvedValueOnce({ success: true, data: { results: [{ id: 5, label: '订单反馈', status: '已验签接收，未自动入账' }] } });
  await button(wrapper, '刷新已接收反馈').trigger('click'); await flushPromises();
  expect(wrapper.text()).toContain('已验签接收，未自动入账');
  api.requestApi.mockResolvedValueOnce({ success: true, data: { business_posted: false } });
  await button(wrapper, '查看').trigger('click'); await flushPromises();
  expect(api.requestApi.mock.calls.at(-1)[0].url).toContain('17/best-notifications/?event_id=5');
  wrapper.unmount();
});
it('allows preview but blocks execution while the server execution gate is off', async () => {
  const wrapper = await open({ execution: false });
  await wrapper.find('select').setValue('QUERY');
  expect(button(wrapper, '执行只读查询').attributes('disabled')).toBeDefined();
  expect(button(wrapper, '检查参数').attributes('disabled')).toBeUndefined();
  wrapper.unmount();
});
