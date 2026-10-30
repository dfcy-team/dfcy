import { beforeEach, expect, it, vi } from 'vitest';
import { shallowMount, flushPromises } from '@vue/test-utils';
const api = vi.hoisted(() => ({ fetchInternalReadonlyClients: vi.fn(), fetchInternalReadonlyCapabilities: vi.fn() }));
vi.mock('../src/api/internalReadonly', async actual => ({ ...(await actual()), ...api }));
vi.mock('element-plus', async actual => ({ ...(await actual()), ElMessage: { error: vi.fn() } }));
import Page from '../src/views/integrations/AIExternalApiSettings.vue';
beforeEach(() => { vi.clearAllMocks(); api.fetchInternalReadonlyClients.mockResolvedValue({ success: true, data: { items: [{ id: 1, name: 'test' }] } }); api.fetchInternalReadonlyCapabilities.mockResolvedValue({ success: true, data: { ready_resources: [] } }); });
it('keeps callers visible when readiness cannot be verified', async () => {
  api.fetchInternalReadonlyCapabilities.mockRejectedValueOnce(new Error('network'));
  const wrapper = shallowMount(Page); await flushPromises();
  expect(wrapper.vm.clients).toHaveLength(1);
  expect(wrapper.vm.readinessKnown).toBe(false);
  expect(wrapper.vm.loading).toBe(false);
  expect(api.fetchInternalReadonlyClients).toHaveBeenCalledWith();
  expect(api.fetchInternalReadonlyCapabilities).toHaveBeenCalledWith();
  wrapper.unmount();
});
it('clears stale callers on failure without losing an independently loaded catalog', async () => {
  const wrapper = shallowMount(Page); await flushPromises();
  api.fetchInternalReadonlyClients.mockRejectedValueOnce(new Error('network'));
  await wrapper.vm.load();
  expect(wrapper.vm.clients).toEqual([]);
  expect(wrapper.vm.readinessKnown).toBe(true);
  expect(wrapper.vm.loading).toBe(false);
  wrapper.unmount();
});
