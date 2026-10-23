import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ strategy: vi.fn(), references: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentStrategy: api.strategy, fetchReplenishmentReferences: api.references }));

import CockpitReplenishmentV2 from '../src/components/supply-chain/CockpitReplenishmentV2.vue';
import OperatingReferenceV2 from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const strategy = { id: 8, version: 2, country_id: 3, name: 'PH strategy', cycle_days: 10, lead_days: 45, safety_days: 35, sales_model: 'weighted', sales_weights: { 7: 50, 15: 30, 30: 20 }, active: true };
const stubs = {
  'el-select': { props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{label}}</option>' },
  'el-date-picker': true, 'el-input-number': true, 'el-switch': true, 'el-input': true,
  'el-alert': { props: ['title'], template: '<p role="alert">{{ title }}</p>' },
  'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue"><slot/></div>' },
  'el-table': { props: ['data'], template: '<div><slot/></div>' }, 'el-table-column': true,
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-checkbox': true, OperatingProductImageV2: true, DocumentSkuV2: true,
};
const success = data => ({ success: true, data });
const line = { sku_id: 7, sku: 'SKU-7', suggested_quantity: 4, available_stock: 8, submitted_demand: 2, draft_reserved_demand: 1, next_eta: { expected_date: '2026-11-02', quantity: 5 }, risk_level: 'replenish', calculation_evidence: { daily_sales_formula: 'A7×50% + A15×30% + A30×20%', sales: { 7: { units: 14, daily_units: 2, weight: 0.5 }, 15: { units: 30, daily_units: 2, weight: 0.3 }, 30: { units: 45, daily_units: 1.5, weight: 0.2 } } } };
const setup = () => { setActivePinia(createPinia()); const auth = useAuthStore(); auth.setCurrentUser({ user_type: 'internal', permissions: ['supply.v2.view'], action_permission_codes: ['supply.v2.view'] }); };
const mountCockpit = countryId => mount(CockpitReplenishmentV2, { props: { countryId }, global: { stubs, directives: { loading: () => {} } } });

describe('cockpit replenishment reference', () => {
  beforeEach(() => {
    setup(); api.strategy.mockReset().mockResolvedValue(success({ configured: true, strategy, sales_end: '2026-10-22' }));
    api.references.mockReset().mockResolvedValue(success({ lines: [line], count: 1, candidate_count: 1, scanned_count: 1, next_offset: 1, has_more: false, generated_at: '2026-10-23T00:00:00Z', formula: 'ceil(max(0,T-I-P-O-Q))' }));
  });

  it('loads the saved country strategy without calculating until requested and routes procurement without creating an order', async () => {
    const wrapper = mountCockpit('3'); await flushPromises();
    expect(api.strategy).toHaveBeenCalledWith('3'); expect(api.references).not.toHaveBeenCalled();
    const reference = wrapper.findComponent(OperatingReferenceV2); expect(reference.props('audience')).toBe('procurement');
    await reference.vm.generate(); await flushPromises();
    expect(api.references).toHaveBeenCalledWith(expect.objectContaining({ country_id: 3, strategy_id: 8, source_kind: 'cycle', quantity_filter: 'positive', limit: 20 }));
    expect(reference.vm.rows[0].submitted_demand).toBe(2); expect(reference.vm.rows[0].draft_reserved_demand).toBe(1); expect(reference.vm.etaDate(line.next_eta)).toBe('2026-11-02');
    await wrapper.findAll('button').find(button => button.text().includes('前往采购协同')).trigger('click');
    expect(wrapper.emitted('procurement')).toHaveLength(1); wrapper.unmount();
  });

  it('keeps cockpit queries country scoped when changing country and clears old rows', async () => {
    const wrapper = mountCockpit('3'); await flushPromises(); const reference = wrapper.findComponent(OperatingReferenceV2);
    await reference.vm.generate(); await flushPromises(); expect(reference.vm.rows).toHaveLength(1);
    await wrapper.setProps({ countryId: '4' }); await flushPromises();
    expect(api.strategy).toHaveBeenLastCalledWith('4'); expect(reference.vm.rows).toEqual([]); expect(reference.vm.selectedRows).toEqual([]);
    wrapper.unmount();
  });
});
