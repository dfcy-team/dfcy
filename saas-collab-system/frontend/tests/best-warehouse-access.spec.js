import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import Access from '../src/components/BestWarehouseAccess.vue';
const api = vi.hoisted(() => ({ requestApi: vi.fn() }));
vi.mock('../src/api/request', () => api);
const stubs = {
  ElAlert: { props: ['title', 'description'], template: '<div role="status">{{ title }} {{ description }}</div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  ElInput: { props: ['modelValue', 'disabled', 'type', 'placeholder'], emits: ['update:modelValue'], template: '<input :value="modelValue" :disabled="disabled" :type="type || \'text\'" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  ElButton: { props: ['disabled', 'nativeType'], template: '<button :disabled="disabled" :type="nativeType || \'button\'"><slot /></button>' },
};
const data = { partner_id: 'TEST-P', customer_code: 'TEST-C', warehouse_code: 'TEST-W', gateway: 'https://warehouse.example.test/ecapi/api/process', version: 3, key_configured: true, authorization_id: 11, status: 'pending', execution_enabled: false };
beforeEach(() => { api.requestApi.mockReset(); api.requestApi.mockResolvedValue({ success: true, data }); });
async function open(props = {}) {
  const wrapper = mount(Access, { props: { warehouseId: 17, canManage: true, canCheck: true, ...props }, global: { stubs } });
  await flushPromises(); return wrapper;
}
it('loads existing configuration without exposing a key or calling the provider', async () => {
  const wrapper = await open();
  expect(wrapper.text()).toContain('已配置 · 待验证');
  expect(wrapper.find('input[type="password"]').element.value).toBe('');
  expect(wrapper.findAll('button')[1].attributes('disabled')).toBeDefined();
  expect(api.requestApi).toHaveBeenCalledTimes(1);
  expect(api.requestApi.mock.calls[0][0]).toMatchObject({ method: 'get', noMockFallback: true });
  wrapper.unmount();
});
it('saves in the warehouse API flow and clears the entered key', async () => {
  const wrapper = await open();
  await wrapper.find('input[type="password"]').setValue('TEST-SECRET-ONLY');
  await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(api.requestApi).toHaveBeenLastCalledWith(expect.objectContaining({ method: 'post', url: '/api/internal/integrations/warehouses/17/best-access/', data: expect.objectContaining({ version: 3, partner_key: 'TEST-SECRET-ONLY' }) }));
  expect(wrapper.find('input[type="password"]').element.value).toBe('');
  expect(wrapper.emitted('changed')).toHaveLength(1);
  wrapper.unmount();
});
it('does not allow viewers to save', async () => {
  const wrapper = await open({ canManage: false });
  expect(wrapper.text()).not.toContain('保存接入配置');
  await wrapper.find('form').trigger('submit');
  expect(api.requestApi).toHaveBeenCalledTimes(1);
  wrapper.unmount();
});
it('shows failures without treating a failed save as connected', async () => {
  const wrapper = await open();
  api.requestApi.mockRejectedValueOnce(new Error('配置版本已改变'));
  await wrapper.find('form').trigger('submit'); await flushPromises();
  expect(wrapper.text()).toContain('配置版本已改变');
  expect(wrapper.text()).not.toContain('连接已验证');
  wrapper.unmount();
});
