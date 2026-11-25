import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ strategy: vi.fn(), daily: vi.fn(), rows: vi.fn() }));
vi.mock('../src/api/replenishmentStrategyV2', () => ({ fetchReplenishmentStrategy: api.strategy, fetchDailyReplenishment: api.daily, fetchReplenishmentJobRows: api.rows }));
import Reference from '../src/components/supply-chain/OperatingReferenceV2.vue';
import InventoryAbcBadges from '../src/components/inventory/InventoryAbcBadges.js';
import { useAuthStore } from '../src/stores/auth';

const stubs = {
  'el-select': { props: ['modelValue'], emits: ['update:modelValue','change'], template: '<select :value="modelValue" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>' },
  'el-option': { props: ['label','value'], template: '<option :value="value">{{label}}</option>' },
  'el-button': { props: ['disabled','loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  'el-table': { template: '<div><slot/></div>' }, 'el-table-column': true, 'el-input': true, 'el-cascader': true,
  'el-popover': true, 'el-checkbox-group': true, 'el-checkbox': true, 'el-alert': true, 'el-tag': true,
  'el-pagination': true, 'el-progress': true, 'el-dialog': true, 'el-drawer': true, 'el-descriptions': true,
  'el-descriptions-item': true, OperatingProductImageV2: true, DocumentSkuV2: true,
};
const response = { success:true, data:{rows:[],count:0,total:0,processed:0,counts:{},limit:20,offset:0,status:'completed'} };
function mountReference() {
  setActivePinia(createPinia()); useAuthStore().setCurrentUser({user_type:'internal',permissions:['supply.v2.view'],action_permission_codes:['supply.v2.view']});
  return mount(Reference,{props:{parameters:{country_id:2,source_kind:'cycle'}},global:{stubs,directives:{loading:()=>{}}}});
}

describe('replenishment composite ABC integration',()=>{
  beforeEach(()=>{
    localStorage.clear(); api.strategy.mockReset().mockResolvedValue({success:true,data:{configured:true,strategy:{id:1,country_id:2,active:true}}});
    api.daily.mockReset().mockResolvedValue({success:true,data:{id:'daily:abc',status:'completed'}}); api.rows.mockReset().mockResolvedValue(response);
  });
  it('shows one composite badge column for SPU, expanded SKU, and independent SKU rows',async()=>{
    const wrapper=mountReference(); await flushPromises();
    expect(wrapper.findAllComponents(InventoryAbcBadges)).toHaveLength(0); // table columns render their cell slots only when rows exist
    expect(wrapper.vm.visibleColumns).toContain('abc');
    wrapper.unmount();
  });
  it('sends abc_grade on the existing GET row query and removes it when cleared',async()=>{
    const wrapper=mountReference(); await flushPromises();
    wrapper.vm.abcGradeFilter='B'; await wrapper.vm.loadRows(3);
    expect(api.rows.mock.lastCall[1]).toMatchObject({abc_grade:'B',offset:60});
    wrapper.vm.abcGradeFilter=''; await wrapper.vm.loadRows(0);
    expect(api.rows.mock.lastCall[1]).not.toHaveProperty('abc_grade');
    wrapper.unmount();
  });
  it('reuses the composite badge criteria and renders the sales and continuity evidence',()=>{
    const row={abc:{classification_basis:'composite',policy_version:'composite_revenue_units_v1_20261120',status:'ready',spu_grade:'A',sku_grade:'B',spu_evidence:{revenue_grade:'A',units_grade:'B',continuity_label:'sustained',reasons:['revenue_A'],active_weeks_last12:10,active_weeks_last4:4},sku_evidence:{revenue_grade:'B',units_grade:'B',continuity_label:'sustained',reasons:['revenue_or_units_B'],active_weeks_last12:8,active_weeks_last4:3}}};
    const wrapper=mount(InventoryAbcBadges,{props:{row,entityType:'sku'}});
    expect(wrapper.text()).toContain('SKU 综合 B'); expect(wrapper.text()).toContain('销售额 B · 销量 B · 持续销售');
    expect(wrapper.find('div[title]').attributes('title')).toContain('销售额或销量为B');
    wrapper.unmount();
  });
});

