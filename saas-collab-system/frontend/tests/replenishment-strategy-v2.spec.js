import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';

const api = vi.hoisted(() => ({ strategy: vi.fn(), save: vi.fn(), references: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({
  fetchReplenishmentStrategy: api.strategy,
  saveReplenishmentStrategy: api.save,
  fetchReplenishmentReferences: api.references,
}));

import Settings from '../src/components/supply-chain/ReplenishmentStrategySettingsV2.vue';
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const ok = data => ({ success: true, data });
const country = { id: 4, name: '菲律宾', country_code: 'PH' };
const configured = { id: 9, version: 3, country_id: 4, name: 'PH常规补货', cycle_days: 10, lead_days: 45, safety_days: 35, sales_model: 'weighted', sales_weights: { 7: 50, 15: 30, 30: 20 }, active: true };
const stubs = {
  'el-form': { template: '<form><slot/></form>' }, 'el-form-item': { template: '<label><slot/></label>' },
  'el-select': { template: '<div><slot/></div>' }, 'el-option': true, 'el-input': true, 'el-input-number': true,
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p role="alert">{{title}}</p>' }, 'el-empty': true,
  'el-date-picker': true, 'el-table': { template: '<div><slot/></div>' }, 'el-table-column': true,
  'el-descriptions': { template: '<div><slot/></div>' }, 'el-descriptions-item': { template: '<div><slot/></div>' },
  'el-dialog': { template: '<div><slot/></div>' }, 'el-tag': true, 'el-checkbox': true,
};

function authorize() {
  const auth = useAuthStore();
  auth.setCurrentUser({ user_type: 'internal', permissions: ['supply.v2.view', 'supply.v2.manage'], action_permission_codes: ['supply.v2.view', 'supply.v2.manage'] });
  return auth;
}

describe('replenishment strategy v2', () => {
  beforeEach(() => {
    vi.clearAllMocks(); setActivePinia(createPinia()); authorize();
    api.strategy.mockResolvedValue(ok({ countries: [country], strategies: [configured], strategy: configured, configured: true, can_manage: true }));
    api.save.mockResolvedValue(ok({ strategy: { ...configured, version: 4 } }));
    api.references.mockResolvedValue(ok({ lines: [], count: 0, candidate_count: 0, scanned_count: 0, next_offset: 0, has_more: false }));
  });

  it('uses optimistic version checks and keeps the edited values after a conflict', async () => {
    const wrapper = mount(Settings, { global: { stubs } }); await flushPromises();
    wrapper.vm.form.cycle_days = 12;
    api.save.mockResolvedValueOnce({ success: false, http_status: 409, message: 'stale version' });
    await wrapper.vm.save();
    expect(api.save).toHaveBeenCalledWith(4, expect.objectContaining({ cycle_days: 12, expected_version: 3 }));
    expect(wrapper.vm.error).toContain('版本冲突');
    expect(wrapper.vm.form.cycle_days).toBe(12);
    wrapper.unmount();
  });

  it('blocks reference generation when the country has no saved strategy', async () => {
    api.strategy.mockResolvedValueOnce(ok({ configured: false, proposed_defaults: { cycle_days: 10, lead_days: 45, safety_days: 35 }, countries: [country] }));
    const wrapper = mount(Reference, { props: { parameters: { country_id: 4, source_kind: 'cycle' }, audience: 'procurement' }, global: { stubs } });
    await flushPromises();
    await wrapper.vm.generate();
    expect(wrapper.vm.strategy).toBeFalsy();
    expect(wrapper.vm.strategyNotice).toContain('尚未配置');
    expect(api.references).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
