import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { ElSelect, ElTable } from 'element-plus';
import Risk from '../src/views/inventory/InventoryWarningRisk537.vue';
import Entry from '../src/views/inventory/InventoryAlertList.vue';
const state=vi.hoisted(()=>({request:vi.fn(),auth:null,push:vi.fn()}));
vi.mock('../src/api/request',()=>({default:(...args)=>state.request(...args)}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>state.auth}));
vi.mock('vue-router',()=>({useRouter:()=>({push:state.push})}));
const country={id:1,name:'Philippines',country_code:'PH'};
const abc=()=>({classification_basis:'composite',policy_version:'composite_revenue_units_v1_20261120',status:'ready',spu_grade:'B',sku_grade:'A',spu_evidence:{revenue_grade:'B',units_grade:'A',continuity_label:'sustained',reasons:[]},sku_evidence:{revenue_grade:'C',units_grade:'A',continuity_label:'sustained',reasons:[]}});
const spu=()=>({spu_id:10,spu_name:'Synthetic SPU',spu_code:'NEW-SPU',legacy_spu_code:'OLD-SPU',sku_count:2,shortage_sku_count:1,warnings:['forecast_stockout'],first_shortage_date:'2026-12-01',abc:abc()});
const sku=(name='NEW-SKU')=>({spu_id:10,sku_id:20,sku_code:name,legacy_sku_code:'OLD-SKU',available_stock:5,daily_sales:'1.236',sales_windows:[{days:7,units:9}],warning:{warnings:['forecast_stockout'],first_shortage_date:'2026-12-01'},abc:abc()});
const metadata=()=>({success:true,data:{countries:[country],results:[],count:0,status:'select_country'}});
const parent=()=>({success:true,data:{countries:[country],run_id:101,status:'ready',results:[spu()],count:1,summary:{forecast_stockout:1,key_variant_shortage:1,supply_risk:0,excess_stock:0,new_product:0}}});
let wrappers=[];
beforeEach(()=>{state.request.mockReset();state.auth=reactive({currentUser:{id:1,tenant_id:1,active_membership_id:1},authorizationStale:false,hasPermission:()=>true});state.request.mockImplementation(async config=>config.params?.spu_id?{success:true,data:{run_id:101,results:[sku()]}}:config.params?.country_id?parent():metadata());});
afterEach(()=>{for(const wrapper of wrappers)wrapper.unmount();wrappers=[];});
async function open(){const wrapper=mount(Risk,{global:{stubs:{DocumentProductImageV2:true}}});wrappers.push(wrapper);await flushPromises();const select=wrapper.findAllComponents(ElSelect)[0];select.vm.$emit('update:modelValue',1);select.vm.$emit('change',1);await flushPromises();return wrapper;}
function expand(wrapper,open=true){wrapper.findAllComponents(ElTable)[0].vm.$emit('expand-change',spu(),open?[spu()]:[]);}

describe('actual warning route restores deployed SPU risk and safe details',()=>{
 it('renders risk summary, new/old product identities, composite evidence and two-decimal SKU daily sales',async()=>{
  const wrapper=await open();expect(wrapper.text()).toContain('Synthetic SPU');expect(wrapper.text()).toContain('NEW-SPU');expect(wrapper.text()).toContain('OLD-SPU');expect(wrapper.text()).toContain('SPU 综合 B');expect(wrapper.text()).toContain('销售额 B · 销量 A');
  expand(wrapper);await flushPromises();expect(wrapper.text()).toContain('NEW-SKU');expect(wrapper.text()).toContain('OLD-SKU');expect(wrapper.text()).toContain('SKU 综合 A');expect(wrapper.text()).toContain('销售额 C · 销量 A');expect(wrapper.text()).toContain('日均 1.24');
  expect(state.request.mock.calls.some(([config])=>config.method==='get'&&config.url==='/api/internal/alerts/inventory/warnings/'&&config.params.spu_id===10&&config.params.country_id===1)).toBe(true);
 });
 it('clears old tenant rows and rejects an ignored-abort detail response',async()=>{
  const wrapper=await open();let finish;state.request.mockImplementation(config=>config.params?.spu_id?new Promise(resolve=>{finish=resolve;}):Promise.resolve(metadata()));expand(wrapper);await flushPromises();
  state.auth.currentUser={id:1,tenant_id:2,active_membership_id:2};await flushPromises();finish({success:true,data:{run_id:101,results:[sku('OLD-TENANT-PRIVATE')]}});await flushPromises();expect(wrapper.text()).not.toContain('OLD-TENANT-PRIVATE');expect(wrapper.text()).not.toContain('Synthetic SPU');
 });
 it('rejects a detail result from a newer snapshot instead of mixing runs',async()=>{
  const wrapper=await open();state.request.mockResolvedValue({success:true,data:{run_id:202,results:[sku('MIXED-RUN-PRIVATE')]}});expand(wrapper);await flushPromises();expect(wrapper.text()).toContain('库存预警已更新');expect(wrapper.text()).not.toContain('MIXED-RUN-PRIVATE');
 });
 it('defaults same-code users with limited data scope to the original follow-up',async()=>{
  state.auth.hasAllDataScopeFor=()=>false;const wrapper=mount(Entry,{global:{stubs:{ElTabs:{template:'<section><slot /></section>'},ElTabPane:{props:['label'],template:'<div>{{ label }}<slot /></div>'},InventoryWarningRisk537:{template:'<div>RISK-CONTENT</div>'},InventoryAlertFollowup537:{template:'<div>ORIGINAL-FOLLOWUP</div>'}}}});wrappers.push(wrapper);await flushPromises();expect(wrapper.text()).toContain('ORIGINAL-FOLLOWUP');expect(wrapper.text()).not.toContain('RISK-CONTENT');
 });
 it('switches an active risk entry to follow-up synchronously when membership loses full scope',async()=>{
  state.auth.currentUser.all_scope_permission_codes=['alerts.view','sales_management.view','sales_management.skus.view','sales_management.supply_summary.view'];state.auth.hasAllDataScopeFor=code=>state.auth.currentUser.all_scope_permission_codes.includes(code);
  const wrapper=mount(Entry,{global:{stubs:{ElTabs:{template:'<section><slot /></section>'},ElTabPane:{props:['label'],template:'<div>{{ label }}<slot /></div>'},InventoryWarningRisk537:{template:'<div>RISK-CONTENT</div>'},InventoryAlertFollowup537:{template:'<div>ORIGINAL-FOLLOWUP</div>'}}}});wrappers.push(wrapper);await flushPromises();expect(wrapper.text()).toContain('RISK-CONTENT');state.auth.currentUser={id:1,tenant_id:2,active_membership_id:2,all_scope_permission_codes:[]};await flushPromises();expect(wrapper.text()).not.toContain('RISK-CONTENT');expect(wrapper.text()).toContain('ORIGINAL-FOLLOWUP');
 });
 it('keeps the original follow-up reachable and default for a viewer without risk permissions',async()=>{
  state.auth.hasPermission=()=>false;const wrapper=mount(Entry,{global:{stubs:{ElTabs:{template:'<section><slot /></section>'},ElTabPane:{props:['label'],template:'<div>{{ label }}<slot /></div>'},InventoryWarningRisk537:true,InventoryAlertFollowup537:{template:'<div>ORIGINAL-FOLLOWUP</div>'}}}});wrappers.push(wrapper);await flushPromises();expect(wrapper.text()).toContain('库存风险');expect(wrapper.text()).toContain('原有预警跟进');expect(wrapper.text()).toContain('ORIGINAL-FOLLOWUP');
 });
});
