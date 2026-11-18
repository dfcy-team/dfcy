import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ strategy: vi.fn(), create: vi.fn(), daily: vi.fn(), status: vi.fn(), rows: vi.fn(), cancel: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentStrategy: api.strategy, fetchDailyReplenishment: api.daily, createReplenishmentJob: api.create, fetchReplenishmentJob: api.status, fetchReplenishmentJobRows: api.rows, cancelReplenishmentJob: api.cancel }));
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const success = (override = {}) => ({ success: true, data: { rows: [], count: 45, total: 120, processed: 120, counts: { positive: 12, zero: 30, unknown: 3, awaiting_procurement: 4, arrival_gap: 2 }, limit: 20, offset: 0, has_more: true, quantity_filter: 'positive', status: 'completed', ...override } });
const strategy = { id: 2, version: 1, country_id: 2, cycle_days: 10, lead_days: 45, safety_days: 35, active: true, sales_weights: { 7: 50, 15: 30, 30: 20 } };
const stubs = {
  'el-cascader': true, 'el-popover': true, 'el-checkbox-group': true,
  'el-select': { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{label}}</option>' }, 'el-input': true, 'el-input-number': true, 'el-date-picker': true,
  'el-button': { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot/></button>' },
  'el-alert': { props: ['title'], template: '<p role="alert">{{title}}</p>' }, 'el-progress': { props: ['percentage'], template: '<div>{{percentage}}</div>' }, 'el-tag': true, 'el-pagination': { props: ['currentPage','pageSize','total'], emits: ['update:currentPage','current-change'], template: '<div />' }, 'el-table': { props: ['data', 'emptyText'], template: '<div><slot/></div>' }, 'el-table-column': true, 'el-checkbox': true,
  'el-dialog': true, 'el-descriptions': true, 'el-descriptions-item': true, OperatingProductImageV2: true, DocumentSkuV2: true,
};
const mountReference = () => {
  setActivePinia(createPinia()); const auth = useAuthStore(); auth.setCurrentUser({ user_type: 'internal', permissions: ['supply.v2.view'], action_permission_codes: ['supply.v2.view'] });
  return mount(Reference, { props: { parameters: { country_id: 2, source_kind: 'cycle' } }, global: { stubs, directives: { loading: () => {} } } });
};

describe('nightly replenishment results and global pagination', () => {
  beforeEach(() => { api.strategy.mockReset().mockResolvedValue({ success: true, data: { configured: true, strategy } }); api.create.mockReset(); api.daily.mockReset().mockResolvedValue({success:true,data:{id:'job-abc',status:'completed',total:120,processed:120,counts:{positive:40,zero:70,unknown:10,awaiting_procurement:4,arrival_gap:2},strategy_version:1,created_at:'2026-10-23T10:00:00Z',updated_at:'2026-10-23T10:00:20Z',parameters:{sales_end:'2026-10-22'},formula:'formula-fixture',revalidation_note:'revalidate-fixture',platform_options:[{platform_type:'shopee'}]}}); api.status.mockReset(); api.rows.mockReset().mockResolvedValue(success()); api.cancel.mockReset().mockResolvedValue({success:true}); });

  it('automatically reads the nightly result and paginates without starting a job', async () => {
    const wrapper = mountReference(); await flushPromises();
    expect(api.daily).toHaveBeenCalledTimes(1); expect(api.daily.mock.calls[0][0]).not.toHaveProperty('search');
    expect(api.create).not.toHaveBeenCalled();
    expect(api.rows).toHaveBeenCalledWith('job-abc', expect.objectContaining({quantity_filter:'observed',limit:20,offset:0}), expect.any(Object));
    expect(wrapper.vm.totalRows).toBe(45); expect(wrapper.vm.summary.positive_count).toBe(12);
    expect(wrapper.vm.summary.awaiting_procurement_count).toBe(4);expect(wrapper.vm.summary.arrival_risk_count).toBe(2);
    wrapper.vm.filter='all'; await wrapper.vm.loadRows(0); expect(api.daily).toHaveBeenCalledTimes(1); expect(api.rows.mock.lastCall[1].quantity_filter).toBe('all');
    await wrapper.vm.loadRows(1); expect(api.rows.mock.lastCall[1].offset).toBe(20); wrapper.unmount();
  });

  it('ignores stale nightly results after switching countries', async () => {
    let resolve;
    api.daily.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const wrapper = mountReference(); await flushPromises();
    api.daily.mockResolvedValueOnce({success:false,status:404});
    await wrapper.setProps({parameters:{country_id:4,source_kind:'cycle'}});
    resolve({success:true,data:{id:'old-country',status:'completed'}});
    await flushPromises();
    expect(wrapper.vm.jobId).toBe('');
    expect(api.rows).not.toHaveBeenCalled();
    expect(api.status).not.toHaveBeenCalled();
    expect(api.create).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('renders backend rows fixture shape and keeps completed-job pagination global', async () => {
    const wrapper=mountReference();await flushPromises();await wrapper.vm.generate();
    api.rows.mockResolvedValueOnce(success({rows:[{sku_id:7,suggested_quantity:3}],count:1,has_more:false,offset:20}));
    await wrapper.vm.loadRows(1);expect(wrapper.vm.rows).toEqual([{sku_id:7,suggested_quantity:3}]);expect(wrapper.vm.page).toBe(2);wrapper.unmount();
  });

  it.each([[403, 'failed'], [410, 'expired']])('clears selected rows after HTTP %i', async (status, terminalState) => {
    const wrapper = mountReference(); await flushPromises();
    wrapper.vm.toggle({sku_id:3,suggested_quantity:2},true);
    api.rows.mockResolvedValueOnce({success:false,http_status:status,message:'unavailable'});
    await wrapper.vm.loadRows(0);
    expect(wrapper.vm.jobStatus).toBe(terminalState);
    expect(wrapper.vm.selectedRows).toEqual([]);
    expect(api.status).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('blocks handoff unless the job is completed and the context is authorized', async () => {
    const wrapper=mountReference();await flushPromises();await wrapper.vm.generate();wrapper.vm.toggle({sku_id:4,suggested_quantity:3},true);
    wrapper.vm.jobStatus='running';wrapper.vm.emitSelection();expect(wrapper.emitted('select')).toBeUndefined();wrapper.vm.jobStatus='completed';await wrapper.setProps({disabled:true});wrapper.vm.emitSelection();expect(wrapper.emitted('select')).toBeUndefined();wrapper.unmount();
  });
});
