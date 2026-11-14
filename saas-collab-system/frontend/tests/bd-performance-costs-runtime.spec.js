import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  BD_PERFORMANCE_CURRENCIES: [{ value: 'CNY', label: '人民币 CNY' }],
  fetchBdPerformance: vi.fn(), formatInfluencerError: (_response, fallback) => fallback
}));
vi.mock('../src/api/influencers', () => api);
import BdPerformancePanel from '../src/views/influencers/BdPerformancePanel.vue';

const stubs = {
  'el-alert': { props: ['title'], template: '<div>{{ title }}<slot /></div>' },
  'el-button': { props: ['disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-card': { template: '<div><slot /></div>' },
  'el-table': {
    props: ['data'],
    provide() { return { tableRows: this.data }; },
    template: '<div><slot /></div>'
  },
  'el-table-column': {
    inject: ['tableRows'],
    props: ['label', 'prop'],
    template: '<span class="column">{{ label }}<template v-if="prop?.startsWith(\'gmv\')"><span v-for="(row, index) in tableRows" :key="index" :data-test="prop"><slot :row="row" /></span></template></span>'
  },
  'el-date-picker': true,
  'el-select': {
    props: ['modelValue'], emits: ['update:modelValue'],
    template: '<select data-test="currency-filter" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option value="CNY">CNY</option><option value="PHP">PHP</option></select>'
  },
  'el-option': true
};
function report(overrides = {}) {
  return { success: true, data: {
    amount_basis: 'estimated_commission_base', cost_basis: 'sample_plus_actual_commissions',
    start_date: '2026-08-01', end_date: '2026-08-31', currency: 'CNY',
    results: [{ owner: 'Demo', sample_count: 1 }],
    totals: {
      sample_cost: '10.0000', sample_cost_complete: true,
      actual_standard_commission: '2.0000', actual_standard_commission_complete: true,
      actual_ads_commission: '0.0000', actual_ads_commission_complete: true,
      total_cost: '12.0000', cost_complete: true, roi: '5.0000'
    }, ...overrides
  } };
}
const panel = () => mount(BdPerformancePanel, { global: { stubs } });

describe('BD three actual cost components runtime', () => {
  beforeEach(() => { vi.clearAllMocks(); api.fetchBdPerformance.mockResolvedValue(report()); });

  it('shows all four core columns, totals and the total-cost denominator', async () => {
    const wrapper = panel(); await flushPromises();
    const labels = wrapper.findAll('.column').map((node) => node.text());
    for (const label of ['送样成本', '实际标准佣金', '实际广告佣金', '总成本']) expect(labels).toContain(label);
    expect(labels).not.toContain('合作单投入');
    expect(wrapper.get('[data-test="bd-cost-summary"]').text()).toContain('CNY 12.00');
    expect(wrapper.text()).toContain('预估计佣金额 / 总成本');
    wrapper.unmount();
  });

  it('shows incomplete known costs and no final ROI when actual commissions are missing', async () => {
    api.fetchBdPerformance.mockResolvedValue(report({ totals: {
      actual_standard_commission: null, known_actual_standard_commission: '2.0000',
      actual_standard_commission_complete: false, missing_actual_standard_commission_count: 3,
      actual_ads_commission: null, known_actual_ads_commission: '0.0000',
      actual_ads_commission_complete: false, missing_actual_ads_commission_count: 5,
      total_cost: null, known_total_cost: '12.0000', cost_complete: false, roi: null
    } }));
    const wrapper = panel(); await flushPromises();
    expect(wrapper.text()).toContain('3 条有效订单明细缺少实际标准佣金');
    expect(wrapper.text()).toContain('5 条有效订单明细缺少实际广告佣金');
    expect(wrapper.text()).toContain('实际佣金列仅展示已核实金额');
    expect(wrapper.get('[data-test="bd-cost-summary"]').text()).toContain('实际标准佣金CNY 2.00');
    expect(wrapper.get('[data-test="bd-cost-summary"]').text()).toContain('实际广告佣金—');
    expect(wrapper.get('[data-test="bd-cost-summary"]').text()).toContain('总成本CNY 12.00');
    expect(wrapper.findAll('.metrics strong').at(-1).text()).toBe('—');
    wrapper.unmount();
  });

  it('shows a labeled reference ROI without substituting for the official result', async () => {
    api.fetchBdPerformance.mockResolvedValue(report({
      source_status: 'incomplete',
      totals: { valid_order_count: 25, known_estimated_commission_base: '2000.1250', known_total_cost: '160.0100', roi: null }
    }));
    const wrapper = panel(); await flushPromises();
    expect(wrapper.findAll('.metrics strong').at(-1).text()).toBe('参考 12.5000x');
    expect(wrapper.text()).toContain('参考 ROI 不代表正式结果');
    wrapper.unmount();
  });

  it('shows verified commission base subtotals in all four columns without showing a final ROI', async () => {
    api.fetchBdPerformance.mockResolvedValue(report({
      source_status: 'incomplete',
      totals: { roi: null },
      results: [{
        owner: 'Demo', valid_order_count: 25,
        gmv: null, gmv_php: null, gmv_myr: null, gmv_thb: null,
        known_estimated_commission_base: '2000.1250',
        known_native_gmv: { PHP: '10000.2400', MYR: '2021.8300', THB: '6076.4000' }
      }]
    }));
    const wrapper = panel(); await flushPromises();
    expect(wrapper.get('[data-test="gmv"]').text()).toBe('CNY 2,000.125');
    expect(wrapper.get('[data-test="gmv_php"]').text()).toBe('PHP 10,000.24');
    expect(wrapper.get('[data-test="gmv_myr"]').text()).toBe('MYR 2,021.83');
    expect(wrapper.get('[data-test="gmv_thb"]').text()).toBe('THB 6,076.40');
    expect(wrapper.findAll('.metrics strong').at(-1).text()).toBe('—');
    wrapper.unmount();
  });

  it('prefers complete amounts, preserves verified zero and does not invent a missing subtotal', async () => {
    api.fetchBdPerformance.mockResolvedValue(report({ results: [{
      owner: 'Demo', gmv: '5', gmv_php: '0', gmv_myr: null, gmv_thb: null,
      known_estimated_commission_base: '2', known_native_gmv: { PHP: '1', MYR: '0' }
    }] }));
    const wrapper = panel(); await flushPromises();
    expect(wrapper.get('[data-test="gmv"]').text()).toBe('CNY 5.00');
    expect(wrapper.get('[data-test="gmv_php"]').text()).toBe('PHP 0.00');
    expect(wrapper.get('[data-test="gmv_myr"]').text()).toBe('—');
    expect(wrapper.get('[data-test="gmv_thb"]').text()).toBe('—');
    wrapper.unmount();
  });

  it('fails visibly against the old sample-only backend, not a plausible old ROI', async () => {
    api.fetchBdPerformance.mockResolvedValue(report({ cost_basis: undefined }));
    const wrapper = panel(); await flushPromises();
    expect(wrapper.text()).toContain('后端成本口径尚未更新');
    expect(wrapper.find('[data-test="bd-cost-summary"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('keeps fetched amounts in their actual currency until the changed filter is refreshed', async () => {
    const wrapper = panel(); await flushPromises();
    await wrapper.get('[data-test="currency-filter"]').setValue('PHP');
    expect(wrapper.get('[data-test="bd-cost-summary"]').text()).toContain('CNY 12.00');
    expect(wrapper.get('[data-test="bd-cost-summary"]').text()).not.toContain('PHP 12.00');
    expect(api.fetchBdPerformance).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
});
