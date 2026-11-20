import { flushPromises, shallowMount } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import Readiness from '../src/views/settings/PlatformIntegrationReadiness.vue';
const mocks = vi.hoisted(() => ({ push: vi.fn(), approval: vi.fn(), repair: vi.fn() }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }));
vi.mock('../src/api/integrations', () => ({
  fetchPlatformIntegrationReadiness: async () => ({ success: true, data: { items: [], global_gates: {} } }),
  setPlatformIntegrationReadonlyApproval: mocks.approval,
  repairPlatformIntegrationContract: mocks.repair,
}));
it('explains BEST blockers and opens only the existing settings page', async () => {
  const wrapper = shallowMount(Readiness);
  await flushPromises();
  const row = { platform_code: 'best_ecapi', blocker_codes: ['best_feature_disabled', 'warehouse_host_not_allowlisted', 'best_contract_invalid', 'best_identity_missing', 'best_gateway_invalid'] };
  const items = wrapper.vm.blockerItems(row);
  expect(items[0].label).toContain('百世真实调用未开启');
  expect(items[1].label).not.toContain('极风');
  expect(items[1].actionHint).not.toContain('极风');
  for (const item of items) expect(item.label).not.toBe(item.code);
  wrapper.vm.openBlockerAction(row, items[0]);
  expect(mocks.push).toHaveBeenCalledWith({ path: '/integrations/production-settings', query: { platform: 'best_ecapi' } });
  expect(mocks.approval).not.toHaveBeenCalled();
  expect(mocks.repair).not.toHaveBeenCalled();
  wrapper.unmount();
});
