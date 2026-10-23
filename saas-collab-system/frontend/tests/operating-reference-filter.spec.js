import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ strategy: vi.fn(), references: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentStrategy: api.strategy, fetchReplenishmentReferences: api.references }));
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const success = (override = {}) => ({ success: true, data: { lines: [], count: 45, candidate_count: 45, scanned_count: 20, offset: 0, next_offset: 20, has_more: true, platform_options: [], generated_at: '2026-10-21', ...override } });
const strategy = { id: 2, version: 1, country_id: 2, cycle_days: 10, lead_days: 45, safety_days: 35, active: true, sales_weights: { 7: 50, 15: 30, 30: 20 } };
const stubs = {
  'el-select': { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{label}}</option>' }, 'el-input': true, 'el-input-number': true, 'el-date-picker': true,
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p role="alert">{{title}}</p>' }, 'el-table': { props: ['data', 'emptyText'], template: '<div><slot/></div>' }, 'el-table-column': true, 'el-checkbox': true,
  'el-dialog': true, 'el-descriptions': true, 'el-descriptions-item': true, OperatingProductImageV2: true, DocumentSkuV2: true,
};
const mountReference = () => {
  setActivePinia(createPinia()); const auth = useAuthStore(); auth.setCurrentUser({ user_type: 'internal', permissions: ['supply.v2.view'], action_permission_codes: ['supply.v2.view'] });
  return mount(Reference, { props: { parameters: { country_id: 2, source_kind: 'cycle' } }, global: { stubs, directives: { loading: () => {} } } });
};

describe('replenishment quantity filters and bounded continuation', () => {
  beforeEach(() => { api.strategy.mockReset().mockResolvedValue({ success: true, data: { configured: true, strategy } }); api.references.mockReset().mockResolvedValue(success()); });

  it('defaults to positive suggestions, pages by backend offsets, and restarts a changed filter at zero', async () => {
    const wrapper = mountReference(); await flushPromises();
    await wrapper.vm.generate(); expect(api.references.mock.calls[0][0]).toMatchObject({ quantity_filter: 'positive', offset: 0, limit: 20 });
    await wrapper.vm.next(); expect(api.references.mock.calls[1][0].offset).toBe(20);
    await wrapper.vm.previous(); expect(api.references.mock.calls[2][0].offset).toBe(0);
    wrapper.vm.filter = 'all'; await wrapper.vm.generate(); expect(api.references.mock.calls[3][0]).toMatchObject({ quantity_filter: 'all', offset: 0 }); wrapper.unmount();
  });

  it('retries a failed continuation at the same offset and renders an empty completed batch', async () => {
    api.references.mockResolvedValueOnce(success()).mockRejectedValueOnce(new Error('temporary'))
      .mockResolvedValueOnce(success({ scanned_count: 5, next_offset: 25, has_more: false, lines: [] }));
    const wrapper = mountReference(); await flushPromises(); await wrapper.vm.generate();
    await wrapper.vm.next(); await flushPromises(); expect(wrapper.vm.error).toBe('temporary');
    await wrapper.vm.load(); await flushPromises();
    expect(api.references.mock.calls[1][0].offset).toBe(20); expect(api.references.mock.calls[2][0].offset).toBe(20);
    expect(wrapper.vm.rows).toEqual([]); expect(wrapper.vm.hasMore).toBe(false); wrapper.unmount();
  });
});
