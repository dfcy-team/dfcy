import { beforeEach, expect, it, vi } from 'vitest';
import { flushPromises, shallowMount } from '@vue/test-utils';
const api = vi.hoisted(() => ({ fetchFeishuConnection: vi.fn(), fetchFeishuOperations: vi.fn(), fetchFeishuResources: vi.fn() }));
vi.mock('../src/api/feishu', async actual => ({ ...(await actual()), ...api }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => false }) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { tab: 'operations', platform: 'shopee', subject_key: 'store:1' } }), useRouter: () => ({ replace: vi.fn() }) }));
import FeishuCollaboration from '../src/views/integrations/FeishuCollaboration.vue';
const mount = () => shallowMount(FeishuCollaboration, { global: { stubs: { AppPage: { template: '<main><slot /></main>' } } } });
beforeEach(() => { vi.clearAllMocks(); api.fetchFeishuOperations.mockResolvedValue({ success: true, data: [{ id: 1 }] }); api.fetchFeishuResources.mockResolvedValue({ success: true, data: [{ id: 2 }] }); });
it('does not pass sales platform or subject scope to Feishu operations', async () => {
  const wrapper = mount(); await flushPromises();
  expect(api.fetchFeishuOperations).toHaveBeenCalledWith({ operation_type: undefined, status: undefined });
  expect(wrapper.vm.canManageCurrent).toBe(false);
  wrapper.unmount();
});
it('keeps the latest tab data when an older response arrives', async () => {
  let finish;
  api.fetchFeishuOperations.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const wrapper = mount(); await flushPromises();
  wrapper.vm.activeTab = 'identity'; await wrapper.vm.loadActive();
  finish({ success: true, data: [{ id: 99 }] }); await flushPromises();
  expect(wrapper.vm.rows).toEqual([{ id: 2 }]);
  expect(api.fetchFeishuResources).toHaveBeenCalledWith('identities');
  wrapper.unmount();
});
it('clears stale rows and releases loading after a rejected request', async () => {
  const wrapper = mount(); await flushPromises();
  expect(wrapper.vm.rows).toHaveLength(1);
  api.fetchFeishuOperations.mockRejectedValueOnce(new Error('network'));
  await wrapper.vm.loadActive();
  expect(wrapper.vm.rows).toEqual([]);
  expect(wrapper.vm.loading).toBe(false);
  expect(wrapper.vm.error).toContain('读取飞书数据失败');
  wrapper.unmount();
});
