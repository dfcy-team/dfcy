import { flushPromises, mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchReferences = vi.hoisted(() => vi.fn());
vi.mock('../src/api/operatingOrdersV2', () => ({ fetchOperatingReferences: fetchReferences }));

import CockpitReplenishmentV2 from '../src/components/supply-chain/CockpitReplenishmentV2.vue';
import OperatingReferenceV2 from '../src/components/supply-chain/OperatingReferenceV2.vue';

const stubs = {
  'el-select': { template: '<select><slot/></select>' }, 'el-option': { template: '<option><slot/></option>' },
  'el-date-picker': true, 'el-input-number': true, 'el-switch': true,
  'el-alert': { props: ['title'], template: '<p>{{ title }}</p>' },
  'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue"><slot/></div>' },
  'el-table': { props: ['data'], template: '<div><slot/></div>' }, 'el-table-column': true,
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-checkbox': true, 'el-input': true, 'el-pagination': true,
  OperatingProductImageV2: true, DocumentSkuV2: true, OperatingDemandV2: true
};
const successful = { success: true, data: { lines: [], candidate_count: 0, scanned_count: 0, next_offset: 0, has_more: false, platform_options: [], generated_at: '2026-10-22T00:00:00Z' } };
const mountCockpit = () => mount(CockpitReplenishmentV2, { props: { countryId: '3' }, global: { stubs, directives: { loading: () => {} } } });

describe('cockpit replenishment panel', () => {
  beforeEach(() => fetchReferences.mockReset().mockResolvedValue(successful));

  it('defaults to the last completed 30 Shanghai business dates and emits parameters with chosen rows', async () => {
    const wrapper = mountCockpit();
    await flushPromises();
    expect(fetchReferences).not.toHaveBeenCalled();
    const ref = wrapper.findComponent(OperatingReferenceV2);
    const params = ref.props('parameters');
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    const expectedEnd = new Date(`${today}T00:00:00Z`); expectedEnd.setUTCDate(expectedEnd.getUTCDate() - 1);
    const end = expectedEnd.toISOString().slice(0, 10);
    const startDate = new Date(`${end}T00:00:00Z`); startDate.setUTCDate(startDate.getUTCDate() - 29);
    expect(params).toMatchObject({ country_id: '3', source_kind: 'cycle', sales_start: startDate.toISOString().slice(0, 10), sales_end: end, target_stock_sales_ratio: 1, include_in_transit: true });
    expect(ref.props('validate')()).toBe(true);
    const rows = [{ sku_id: 7, suggested_quantity: 4 }];
    ref.vm.$emit('select', rows);
    expect(wrapper.emitted('select')[0][0]).toEqual({ parameters: { ...params }, rows });
    wrapper.unmount();
  });

  it('blocks invalid country, dates and ratios before making a request', async () => {
    const wrapper = mountCockpit();
    const ref = wrapper.findComponent(OperatingReferenceV2);
    const params = ref.props('parameters');
    const validate = ref.props('validate');
    params.country_id = null; expect(validate()).toBe(false); await nextTick(); expect(wrapper.text()).toContain('有效国家');
    params.country_id = 3; params.sales_end = '2999-01-01'; expect(validate()).toBe(false); await nextTick(); expect(wrapper.text()).toContain('已完成');
    params.sales_end = params.sales_start; params.sales_start = '2025-01-01'; expect(validate()).toBe(false); await nextTick(); expect(wrapper.text()).toContain('366 天');
    params.sales_start = '2026-10-01'; params.sales_end = '2026-10-10'; params.target_stock_sales_ratio = 0; expect(validate()).toBe(false); await nextTick(); expect(wrapper.text()).toContain('库销比');
    await ref.vm.generate();
    expect(fetchReferences).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('shows warehouse evidence from the loaded row and marks incomplete coverage for review', async () => {
    const row = { sku: 'SKU-1', product_name: '测试商品', coverage_days: '12.50', inventory_complete: false,
      warehouses: [{ id: 1, name: '主仓', available_qty: '8', snapshot_at: '2026-10-21T03:00:00Z', issues: ['stale_inventory_snapshot'] }],
      blocking_issues: ['stale_inventory_snapshot'] };
    const wrapper = mount(OperatingReferenceV2, { props: { parameters: { country_id: 3 }, validate: () => true }, global: { stubs } });
    expect(wrapper.vm.coverage(row)).toBe('待核对');
    wrapper.vm.openEvidence(row);
    expect(wrapper.vm.evidenceVisible).toBe(true);
    expect(wrapper.vm.evidenceRow.warehouses[0]).toMatchObject({ name: '主仓', available_qty: '8', snapshot_at: '2026-10-21T03:00:00Z' });
    expect(wrapper.vm.evidenceRow.blocking_issues).toContain('stale_inventory_snapshot');
    expect(fetchReferences).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
