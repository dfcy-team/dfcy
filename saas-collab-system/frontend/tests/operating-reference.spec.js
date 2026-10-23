import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ strategy: vi.fn(), references: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentStrategy: api.strategy, fetchReplenishmentReferences: api.references }));
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const configured = (countryId = 3, extra = {}) => ({ id: countryId + 10, version: 2, country_id: countryId, name: '测试策略', cycle_days: 10, lead_days: 45, safety_days: 35, sales_model: 'weighted', sales_weights: { 7: 50, 15: 30, 30: 20 }, active: true, ...extra });
const result = (lines = [], extra = {}) => ({ success: true, data: { lines, count: 40, candidate_count: 40, scanned_count: 20, next_offset: 20, has_more: true, platform_options: [{ platform_type: 'shopee', name: 'Shopee' }], generated_at: '2026-10-21T00:00:00Z', formula: 'ceil(max(0,T-I-P-O-Q))', ...extra } });
const row = (id, qty) => ({ sku_id: id, sku: `SKU-${id}`, sku_code: `SKU-${id}`, suggested_quantity: qty, submitted_demand: 2, draft_reserved_demand: 3, next_eta: { expected_date: '2026-11-01', quantity: 4 } });
const stubs = {
  'el-select': { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{label}}</option>' }, 'el-input': { props: ['disabled'], template: '<input :disabled="disabled" />' }, 'el-input-number': true, 'el-date-picker': true,
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p role="alert">{{title}}</p>' }, 'el-table': { props: ['data', 'emptyText'], template: '<div><slot/></div>' }, 'el-table-column': true, 'el-checkbox': true,
  'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue"><slot/></div>' }, 'el-descriptions': { template: '<div><slot/></div>' }, 'el-descriptions-item': { props: ['label'], template: '<div><span>{{label}}</span><slot/></div>' },
  OperatingProductImageV2: true, DocumentSkuV2: true,
};
const parameters = country_id => ({ country_id, source_kind: 'cycle' });
function setup() { setActivePinia(createPinia()); const auth = useAuthStore(); auth.setCurrentUser({ user_type: 'internal', permissions: ['supply.v2.view'], action_permission_codes: ['supply.v2.view'] }); return auth; }
const create = countryId => mount(Reference, { props: { parameters: parameters(countryId), audience: 'operator' }, global: { stubs, directives: { loading: () => {} } } });

describe('country-scoped operating replenishment reference', () => {
  beforeEach(() => {
    setup(); api.strategy.mockReset().mockImplementation(countryId => Promise.resolve({ success: true, data: { configured: true, strategy: configured(Number(countryId)), sales_end: '2026-10-22' } }));
    api.references.mockReset().mockResolvedValue(result([row(1, 5), row(2, 0), row(3, null)]));
  });
  afterEach(() => vi.restoreAllMocks());

  it('does no calculation on open, keeps selections across bounded pages, and emits strategy evidence', async () => {
    const wrapper = create(3); await flushPromises(); expect(api.references).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('订货间隔 10 天');
    await wrapper.vm.generate(); wrapper.vm.selectPage();
    expect(api.references.mock.calls[0][0]).toMatchObject({ country_id: 3, strategy_id: 13, source_kind: 'cycle', quantity_filter: 'positive', limit: 20, offset: 0 });
    expect(wrapper.vm.selectedRows.map(item => item.sku_id)).toEqual([1]);
    api.references.mockResolvedValueOnce(result([row(4, 8)])); await wrapper.vm.next(); wrapper.vm.selectPage();
    expect(api.references.mock.lastCall[0].offset).toBe(20); expect(wrapper.vm.selectedRows.map(item => item.sku_id)).toEqual([1, 4]);
    wrapper.vm.emitSelection(); expect(wrapper.emitted('select')[0][0]).toMatchObject({ parameters: { strategy_id: 13, source_kind: 'cycle' }, rows: [{ sku_id: 1 }, { sku_id: 4 }] });
    expect(wrapper.vm.rows[0].draft_reserved_demand).toBe(3); wrapper.unmount();
  });

  it('discards late results and clears selections when country or account changes', async () => {
    const auth = useAuthStore(), wrapper = create(3); await flushPromises(); await wrapper.vm.generate(); wrapper.vm.selectPage();
    let finish; api.references.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const pending = wrapper.vm.next(); await wrapper.setProps({ parameters: parameters(4) }); await flushPromises();
    finish(result([row(99, 10)])); await pending; expect(wrapper.vm.rows).toEqual([]); expect(wrapper.vm.selectedRows).toEqual([]); expect(wrapper.vm.strategy.country_id).toBe(4);
    await wrapper.vm.generate(); wrapper.vm.selectPage(); auth.setCurrentUser({ id: 99, user_type: 'internal', permissions: ['supply.v2.view'], action_permission_codes: ['supply.v2.view'] }); await flushPromises();
    expect(wrapper.vm.rows).toEqual([]); expect(wrapper.vm.selectedRows).toEqual([]); wrapper.unmount();
  });

  it('keeps zero and unknown quantities separate and caps selection at 100', async () => {
    const wrapper = create(3); await flushPromises(); await wrapper.vm.generate();
    wrapper.vm.filter = 'unknown'; await wrapper.vm.generate(); expect(api.references.mock.lastCall[0].quantity_filter).toBe('unknown');
    api.references.mockResolvedValueOnce(result([row(5, 0)])); wrapper.vm.filter = 'zero'; await wrapper.vm.generate(); expect(api.references.mock.lastCall[0].quantity_filter).toBe('zero');
    for (let id = 1; id <= 101; id++) wrapper.vm.toggle(row(id, 1), true);
    expect(wrapper.vm.selectedRows).toHaveLength(100); expect(wrapper.vm.error).toContain('100');
    wrapper.vm.toggle(row(1, 1), false); expect(wrapper.vm.selectedRows).toHaveLength(99); wrapper.unmount();
  });

  it('requires an explicit platform and never treats platform contribution as country stock', async () => {
    const wrapper = create(3); await flushPromises(); await wrapper.vm.generate();
    wrapper.vm.analysisMode = 'platform'; wrapper.vm.platformType = ''; await Promise.resolve(); await wrapper.vm.generate(); expect(wrapper.vm.error).toContain('请先选择平台');
    wrapper.vm.platformType = 'shopee'; api.references.mockResolvedValueOnce(result([row(1, 12)])); await wrapper.vm.generate();
    expect(api.references.mock.lastCall[0]).toMatchObject({ analysis_mode: 'platform', platform_type: 'shopee' });
    wrapper.vm.analysisMode = 'country'; await wrapper.vm.generate(); expect(api.references.mock.lastCall[0]).not.toHaveProperty('platform_type'); wrapper.unmount();
  });

  it('does not present unknown shortage as safe and substitutes the actual quantities', async () => {
    const wrapper=create(3); await flushPromises();
    expect(wrapper.vm.shortageLabel({risk_level:'data_check',calculation_evidence:{first_shortage_date:null}})).toBe('数据待核对');
    expect(wrapper.vm.shortageLabel({risk_level:'new_or_zero_sales',calculation_evidence:{}})).toContain('近期无销量');
    const formula=wrapper.vm.substitutedFormula({calculation_evidence:{target_stock:1584,available_stock:400,valid_incoming:500,submitted_demand:200,draft_reserved_demand:50,suggested_quantity:434}});
    expect(formula).toContain('1,584－400－500－200－50'); expect(formula).toContain('434');
    wrapper.unmount();
  });

  it('shows the calculation evidence for loaded items', async () => {
    const wrapper = create(3); await flushPromises(); await wrapper.vm.generate(); const loaded = wrapper.vm.rows[0];
    wrapper.vm.openEvidence(loaded); await flushPromises();
    expect(wrapper.vm.evidenceRow).toEqual(loaded); expect(wrapper.text()).toContain('公式代入'); wrapper.unmount();
  });

  it('translates lifecycle and sales status, shows actual platform windows, weights, and reminder-line evidence', async () => {
    const wrapper = create(3); await flushPromises();
    const item = { ...row(8, 12), product_status: 'active/on_sale', platform_analysis: { platform_type: 'shopee', contributes_to_suggestion: false, windows: { 7: { units: 11, daily_units: 1.57 }, 15: { units: 20, daily_units: 1.33 }, 30: { units: 30, daily_units: 1 } } }, calculation_evidence: { sales: { 7: { units: 21, daily_units: 3, weight: 50 }, 15: { units: 30, daily_units: 2, weight: 30 }, 30: { units: 45, daily_units: 1.5, weight: 20 } }, reminder_stock: '42', reminder_incoming: '7', needs_replenishment: true, first_shortage_date: '2026-11-04', arrival_gap: true } };
    expect(wrapper.vm.productStatusLabel(item.product_status)).toBe('生命周期：正常／销售状态：销售中');
    expect(wrapper.vm.weightPercent(50)).toBe('50%');
    expect(wrapper.vm.platformRows(item)).toEqual([{ period: '近7天', units: 11, daily_units: 1.57 }, { period: '近15天', units: 20, daily_units: 1.33 }, { period: '近30天', units: 30, daily_units: 1 }]);
    wrapper.vm.openEvidence(item); await flushPromises();
    expect(wrapper.text()).toContain('平台 shopee 的销量只用于贡献分析');
    expect(wrapper.text()).toContain('提醒线预测需求（到仓前＋安全库存）'); expect(wrapper.text()).toContain('42');
    expect(wrapper.text()).toContain('首次预计缺货日期'); expect(wrapper.text()).toContain('2026-11-04');
    expect(wrapper.vm.yesNo(item.calculation_evidence.arrival_gap)).toBe('是'); wrapper.unmount();
  });
});
