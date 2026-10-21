import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ evaluate: vi.fn(), fetch: vi.fn(), preview: vi.fn(), create: vi.fn(), stale: false, canManage: true, push: vi.fn(), key: 0 }));
vi.mock('../src/api/inventoryDecisions', () => ({
  evaluateCountryInventoryAlerts: mocks.evaluate,
  fetchCountryInventoryDecisions: mocks.fetch,
  previewCountryOperatingOrder: mocks.preview,
  createCountryOperatingOrder: mocks.create,
  createIdempotencyKey: () => `key-${++mocks.key}`
}));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isInternal: true, authorizationStale: mocks.stale, hasPermission: () => mocks.canManage }) }));
vi.mock('vue-router', async original => ({ ...(await original()), useRouter: () => ({ push: mocks.push }) }));

import { flushPromises, mount } from '@vue/test-utils';
import CountryInventoryDecisions from '../src/components/inventory/CountryInventoryDecisions.vue';

const sample = { sku_id: 7, sku: 'SKU-7', legacy_sku_code: 'OLD-7', product_name: 'Item', available_stock: null, inventory_complete: false, suggested_quantity: null, daily_sales: null, coverage_days: null, needs_review: true, decision_state: 'pending', replenishment_status: 'pending', evaluation_status: 'pending', evaluated_at: null, data_at: null, blocking_issues: ['missing_inventory_snapshot', 'collection_coverage_unproven'], warehouses: [{ id: 1, name: 'Main', available_qty: null, snapshot_at: null, issues: ['missing'] }], pipeline: { production_unshipped: null, effective_incoming: null, open_operating_demand: null }, wms_in_transit_stock: null, sales_windows: [{ days: 7, units: null, daily_units: null, amount_by_currency: {} }, { days: 15, units: '5', daily_units: '0.33', amount_by_currency: { USD: '12.00' } }, { days: 30, units: '10', daily_units: '0.33', amount_by_currency: { USD: '24.00' } }], issues: ['inventory_incomplete'] };
const data = (override = {}) => ({ success: true, data: { countries: [{ id: 2, name: 'US', country_code: 'US' }], results: [sample], count: 1, permissions: { can_preview: true, can_create: true }, parameters: {}, ...override } });
const stubs = {
  AppPage: { template: '<main><slot/></main>' }, DocumentSkuV2: { template: '<span>{{sku}} {{legacySkuCode}}</span>', props: ['sku', 'legacySkuCode'] }, DocumentProductImageV2: true,
  'el-alert': { props: ['title'], template: '<p>{{title}}</p>' }, 'el-select': { template: '<div><slot/></div>' }, 'el-option': true,
  'el-input': { template: '<input />' }, 'el-input-number': { template: '<input />' }, 'el-button': { props: ['disabled','loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-table': { props: ['data', 'emptyText'], template: '<div><slot/><span v-if="!data.length">{{emptyText}}</span><span v-for="row in data" :key="row.sku_id">{{row.sku}} {{row.available_stock ?? "待核对"}} {{row.suggested_quantity ?? "待核对"}} {{(row.blocking_issues || []).join("、")}}</span></div>' },
  'el-table-column': { props: ['label'], template: '<div><slot :row="{}" :$index="0"/></div>' }, 'el-pagination': true, 'el-tag': { template: '<span><slot/></span>' },
  'el-dialog': { props: ['modelValue'], emits: ['update:modelValue'], template: '<section v-if="modelValue"><slot/><slot name="footer"/></section>' }, 'el-form': { template: '<form><slot/></form>' }, 'el-form-item': { template: '<label><slot/></label>' }, 'el-date-picker': true
};
function mountPage(mode = 'replenishment') { return mount(CountryInventoryDecisions, { props: { mode }, global: { stubs } }); }

describe('country inventory decisions', () => {
  beforeEach(() => {
    mocks.evaluate.mockReset(); mocks.fetch.mockReset().mockResolvedValue(data({ results: [], count: 0 })); mocks.preview.mockReset(); mocks.create.mockReset(); mocks.push.mockReset(); mocks.stale = false; mocks.canManage = true; mocks.key = 0;
  });

  it('shows missing stock and recommendation as pending verification rather than zero', async () => {
    mocks.fetch.mockResolvedValue(data()); const wrapper = mountPage(); await flushPromises();
    wrapper.vm.countryId = 2; await wrapper.vm.load(); await flushPromises();
    expect(wrapper.text()).toContain('待核对'); expect(wrapper.text()).not.toMatch(/可用库存\s*0/); expect(wrapper.text()).not.toMatch(/建议数量\s*0/); wrapper.unmount();
  });

  it('hides write controls for read-only and stale authorization', async () => {
    mocks.canManage = false; mocks.fetch.mockResolvedValue(data()); let wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).not.toContain('预览并复核'); wrapper.unmount();
    mocks.canManage = true; mocks.stale = true; wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).not.toContain('预览并复核'); wrapper.unmount();
  });

  it('discards an older country response after a newer response', async () => {
    let resolveOld, calls = 0; mocks.fetch.mockImplementation(() => { calls++; if (calls === 2) return new Promise(resolve => { resolveOld = resolve; }); if (calls === 3) return Promise.resolve(data({ results: [{ ...sample, sku: 'NEW' }] })); return Promise.resolve(data({ results: [], count: 0 })); });
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2;
    const old = wrapper.vm.load(); const newer = wrapper.vm.load(); await newer;
    resolveOld(data({ results: [{ ...sample, sku: 'OLD' }] })); await old; await flushPromises();
    expect(wrapper.text()).toContain('NEW'); expect(wrapper.text()).not.toContain('OLD-7 OLD'); wrapper.unmount();
  });

  it('previews, reviews, then creates a draft once; failed create retries with the same key and payload', async () => {
    mocks.fetch.mockResolvedValue(data()); mocks.preview.mockResolvedValue(data({ preview_token: 'test-preview-1', lines: [{ sku_id: 7, sku: 'SKU-7', suggested_quantity: 4, issues: ['check'] }] }));
    let failFirst; mocks.create.mockImplementationOnce(() => new Promise(resolve => { failFirst = resolve; })).mockResolvedValueOnce({ success: true, data: { id: 9, number: 'ORD-9', status: 'draft' } });
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2; wrapper.vm.selectedRows = [sample]; await wrapper.vm.preview();
    expect(mocks.preview).toHaveBeenCalledOnce(); expect(wrapper.vm.reviewOpen).toBe(true);
    wrapper.vm.notes = '人工确认'; wrapper.vm.planRevision = 'V1'; const firstAttempt = wrapper.vm.createDraft(); await wrapper.vm.createDraft();
    expect(mocks.create).toHaveBeenCalledOnce(); failFirst({ success: false, http_status: null, message: 'network' }); await firstAttempt;
    await wrapper.vm.createDraft();
    const calls = mocks.create.mock.calls; expect(calls).toHaveLength(2); expect(calls[0][0]).toEqual(calls[1][0]); expect(calls[0][1]).toBe(calls[1][1]);
    expect(calls[1][0]).toMatchObject({ country_id: 2, source_kind: 'cycle', preview_token: 'test-preview-1', lines: [{ sku_id: 7, quantity: 4 }] });
    expect(mocks.push).toHaveBeenCalledWith('/sales-management/operating-orders'); wrapper.unmount();
  });
  it('evaluates only selected real observations when explicitly requested', async () => {
    mocks.fetch.mockResolvedValue(data({permissions:{can_preview:true,can_create:true,can_evaluate:true}}));
    mocks.evaluate.mockResolvedValue({success:true,data:{created:1,updated:0,skipped:[],rule_count:1}});
    const wrapper=mountPage(); await flushPromises();
    expect(mocks.evaluate).not.toHaveBeenCalled();
    wrapper.vm.countryId=2; wrapper.vm.selectedRows=[sample]; await wrapper.vm.evaluateAlerts();
    expect(mocks.evaluate).toHaveBeenCalledWith({country_id:2,sku_ids:[7],window_days:30,target_days:60});
    expect(mocks.create).not.toHaveBeenCalled(); wrapper.unmount();
  });

  it('shows a readable timeout and retries the same query without write actions', async () => {
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2;
    mocks.fetch.mockRejectedValueOnce(Object.assign(new Error('timeout of 10000ms exceeded'), { code: 'ECONNABORTED' }));
    await wrapper.vm.load(); await flushPromises();
    expect(wrapper.text()).toContain('经营汇总读取超时');
    expect(wrapper.text()).not.toContain('timeout of 10000ms');
    expect(wrapper.text()).toContain('查询未完成，请重试；当前不能判断是否有库存');
    expect(wrapper.text()).not.toContain('请选择国家并查询经营汇总');
    const previous = mocks.fetch.mock.calls.at(-1)[0];
    mocks.fetch.mockResolvedValueOnce(data());
    await wrapper.findAll('button').find(button => button.text() === '重试当前查询').trigger('click'); await flushPromises();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toEqual(previous);
    expect(wrapper.text()).not.toContain('经营汇总读取超时');
    expect(mocks.create).not.toHaveBeenCalled(); expect(mocks.evaluate).not.toHaveBeenCalled(); wrapper.unmount();
  });

  it('handles the normalized timeout returned by the real API helper', async () => {
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2;
    mocks.fetch.mockResolvedValueOnce({ success:false, code:'HTTP_NETWORK_ERROR', message:'timeout of 30000ms exceeded', data:null });
    await wrapper.vm.load(); await flushPromises();
    expect(wrapper.text()).toContain('经营汇总读取超时');
    expect(wrapper.text()).not.toContain('timeout of 30000ms'); wrapper.unmount();
  });

  it('uses backend decision buckets and keeps zero quantity visible in the ready bucket', async () => {
    const zero = { ...sample, available_stock: 12, inventory_complete: true, suggested_quantity: 0, decision_state: 'ready', replenishment_status: 'sufficient', blocking_issues: [] };
    mocks.fetch.mockResolvedValue(data({ results: [zero], count: 1, summary: { ready: 1, positive: 0 } }));
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2; await wrapper.vm.load();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toMatchObject({ country_id: 2, decision_state: 'positive' });
    await wrapper.vm.setDecisionState('ready'); await flushPromises();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toMatchObject({ country_id: 2, decision_state: 'ready' });
    expect(wrapper.text()).toContain('SKU-7'); expect(wrapper.text()).toContain('12'); expect(wrapper.text()).toContain('0');
    wrapper.unmount();
  });

  it('shows all pending reasons and cannot expose order draft controls from pending mode', async () => {
    mocks.fetch.mockResolvedValue(data()); const wrapper = mountPage('pending'); await flushPromises();
    expect(mocks.fetch.mock.calls[0][0]).toMatchObject({ decision_state: 'pending' });
    wrapper.vm.countryId = 2; await wrapper.vm.load(); await flushPromises();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toMatchObject({ decision_state: 'pending' });
    expect(wrapper.text()).toContain('missing_inventory_snapshot'); expect(wrapper.text()).toContain('collection_coverage_unproven');
    expect(wrapper.text()).not.toContain('预览并复核'); expect(wrapper.text()).not.toContain('创建运营订货草稿');
    wrapper.unmount();
  });

  it('treats a building snapshot as pending work and polls the unchanged query', async () => {
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2;
    mocks.fetch.mockResolvedValueOnce(data({ query_state: 'building', processed_count: 4, results: [], count: 0 }));
    vi.useFakeTimers();
    await wrapper.vm.load();
    expect(wrapper.vm.rows).toEqual([]); expect(wrapper.text()).toContain('已处理 4 个 SKU');
    mocks.fetch.mockResolvedValueOnce(data({ query_state: 'ready', results: [sample], count: 1 }));
    await vi.advanceTimersByTimeAsync(3000); await flushPromises();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toMatchObject({ country_id: 2, decision_state: 'positive' });
    expect(wrapper.vm.rows).toHaveLength(1);
    vi.useRealTimers(); wrapper.unmount();
  });

  it('opens the pending tab through its visible control and requests a fresh check explicitly', async () => {
    mocks.fetch.mockResolvedValue(data()); const wrapper = mountPage(); await flushPromises();
    wrapper.vm.countryId = 2;
    const pendingTab = wrapper.findAll('button').find(button => button.text().includes('待核对数据'));
    expect(pendingTab).toBeDefined();
    await pendingTab.trigger('click'); await flushPromises();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toMatchObject({ country_id: 2, decision_state: 'pending' });
    expect(wrapper.text()).not.toContain('预览并复核');
    await wrapper.findAll('button').find(button => button.text() === '重新校验数据').trigger('click'); await flushPromises();
    expect(mocks.fetch.mock.calls.at(-1)[0]).toMatchObject({ refresh: true });
    wrapper.unmount();
  });

  it('shows completed rows while the remaining snapshot is building', async () => {
    const wrapper = mountPage(); await flushPromises(); wrapper.vm.countryId = 2;
    mocks.fetch.mockResolvedValueOnce(data({query_state:'building', processed_count:100, results:[sample], count:1}));
    await wrapper.vm.load();
    expect(wrapper.vm.rows).toHaveLength(1); expect(wrapper.vm.queryBuilding).toBe(true);
    expect(wrapper.text()).toContain('已处理 100 个 SKU');
    wrapper.unmount();
  });

});
