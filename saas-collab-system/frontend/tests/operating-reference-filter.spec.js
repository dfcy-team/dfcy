import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ strategy: vi.fn(), create: vi.fn(), status: vi.fn(), rows: vi.fn(), cancel: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentStrategy: api.strategy, createReplenishmentJob: api.create, fetchReplenishmentJob: api.status, fetchReplenishmentJobRows: api.rows, cancelReplenishmentJob: api.cancel }));
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
import { useAuthStore } from '../src/stores/auth';

const success = (override = {}) => ({ success: true, data: { rows: [], count: 45, total: 120, processed: 120, counts: { positive: 12, zero: 30, unknown: 3, awaiting_procurement: 4, arrival_gap: 2 }, limit: 20, offset: 0, has_more: true, quantity_filter: 'positive', status: 'completed', ...override } });
const strategy = { id: 2, version: 1, country_id: 2, cycle_days: 10, lead_days: 45, safety_days: 35, active: true, sales_weights: { 7: 50, 15: 30, 30: 20 } };
const stubs = {
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

describe('replenishment background jobs and global pagination', () => {
  beforeEach(() => { api.strategy.mockReset().mockResolvedValue({ success: true, data: { configured: true, strategy } }); api.create.mockReset().mockResolvedValue({success:true,data:{id:'job-abc',status:'completed',total:120,processed:120,counts:{positive:40,zero:70,unknown:10,awaiting_procurement:4,arrival_gap:2},strategy_version:1,created_at:'2026-10-23T10:00:00Z',updated_at:'2026-10-23T10:00:20Z',parameters:{sales_end:'2026-10-22'},formula:'formula-fixture',revalidation_note:'revalidate-fixture',platform_options:[{platform_type:'shopee'}]}}); api.status.mockReset(); api.rows.mockReset().mockResolvedValue(success()); api.cancel.mockReset().mockResolvedValue({success:true}); });

  it('creates one country job then filters and paginates globally without recalculation', async () => {
    const wrapper = mountReference(); await flushPromises();
    await wrapper.vm.generate(); expect(api.create).toHaveBeenCalledTimes(1); expect(api.create.mock.calls[0][0]).not.toHaveProperty('search');
    expect(api.rows).toHaveBeenCalledWith('job-abc', expect.objectContaining({quantity_filter:'positive',limit:20,offset:0}), expect.any(Object));
    expect(wrapper.vm.totalRows).toBe(45); expect(wrapper.vm.summary.positive_count).toBe(12);
    expect(wrapper.vm.summary.awaiting_procurement_count).toBe(4);expect(wrapper.vm.summary.arrival_risk_count).toBe(2);expect(wrapper.vm.observationStart).toBe('2026-10-23T10:00:00Z');expect(wrapper.vm.observationEnd).toBe('2026-10-23T10:00:20Z');expect(wrapper.vm.salesEnd).toBe('2026-10-22');expect(wrapper.vm.platformOptions).toEqual([{platform_type:'shopee'}]);
    wrapper.vm.filter='all'; await wrapper.vm.loadRows(0); expect(api.create).toHaveBeenCalledTimes(1); expect(api.rows.mock.lastCall[1].quantity_filter).toBe('all');
    await wrapper.vm.loadCurrentPage(2); expect(api.rows.mock.lastCall[1].offset).toBe(20); wrapper.unmount();
  });

  it('polls queued work without overlap and stops polling when the country context changes', async () => {
    vi.useFakeTimers(); api.create.mockResolvedValue({success:true,data:{id:'job-uuid',status:'queued',total:100,processed:0}});
    let finish; api.status.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
    const wrapper=mountReference(); await flushPromises(); await wrapper.vm.generate(); await vi.advanceTimersByTimeAsync(2000);
    expect(api.status).toHaveBeenCalledTimes(1); await wrapper.setProps({parameters:{country_id:4,source_kind:'cycle'}}); finish?.({success:true,data:{id:'job-uuid',status:'completed',total:100,processed:100}}); await flushPromises();
    expect(wrapper.vm.jobId).toBe(''); expect(api.rows).not.toHaveBeenCalled(); wrapper.unmount(); vi.useRealTimers();
  });

  it('renders backend rows fixture shape and keeps completed-job pagination global', async () => {
    const wrapper=mountReference();await flushPromises();await wrapper.vm.generate();
    api.rows.mockResolvedValueOnce(success({rows:[{sku_id:7,suggested_quantity:3}],count:1,has_more:false,offset:20}));
    await wrapper.vm.loadRows(1);expect(wrapper.vm.rows).toEqual([{sku_id:7,suggested_quantity:3}]);expect(wrapper.vm.page).toBe(2);wrapper.unmount();
  });

  it('stops polling on terminal permission responses and expires rows on HTTP 410', async () => {
    vi.useFakeTimers();api.create.mockResolvedValue({success:true,data:{id:'job-terminal',status:'queued',total:20,processed:0}});api.status.mockResolvedValue({success:false,http_status:403,message:'scope changed'});
    const waiting=mountReference();await flushPromises();await waiting.vm.generate();await vi.advanceTimersByTimeAsync(2000);await flushPromises();
    expect(waiting.vm.jobStatus).toBe('failed');expect(waiting.vm.selectedRows).toEqual([]);await vi.advanceTimersByTimeAsync(10000);expect(api.status).toHaveBeenCalledTimes(1);waiting.unmount();
    vi.useRealTimers();
    api.create.mockResolvedValue({success:true,data:{id:'job-complete',status:'completed',total:1,processed:1,counts:{positive:1}}});const completed=mountReference();await flushPromises();await completed.vm.generate();completed.vm.selectPage();expect(completed.vm.selectedRows).toHaveLength(0);
    completed.vm.toggle({sku_id:3,suggested_quantity:2},true);api.rows.mockResolvedValueOnce({success:false,http_status:410,message:'expired'});await completed.vm.loadRows(0);
    expect(completed.vm.jobStatus).toBe('expired');expect(completed.vm.selectedRows).toEqual([]);completed.unmount();
  });

  it('blocks handoff unless the job is completed and the context is authorized', async () => {
    const wrapper=mountReference();await flushPromises();await wrapper.vm.generate();wrapper.vm.toggle({sku_id:4,suggested_quantity:3},true);
    wrapper.vm.jobStatus='running';wrapper.vm.emitSelection();expect(wrapper.emitted('select')).toBeUndefined();wrapper.vm.jobStatus='completed';await wrapper.setProps({disabled:true});wrapper.vm.emitSelection();expect(wrapper.emitted('select')).toBeUndefined();wrapper.unmount();
  });
});
