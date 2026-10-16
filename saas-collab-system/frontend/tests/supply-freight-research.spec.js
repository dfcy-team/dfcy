import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
const mocks=vi.hoisted(()=>({request:vi.fn(),auth:{authorizationStale:false,hasPermission:()=>true}}));
vi.mock('../src/api/request',()=>({requestApi:mocks.request}));
vi.mock('../src/stores/auth',async()=>{const {reactive}=await import('vue');mocks.auth=reactive(mocks.auth);return {useAuthStore:()=>mocks.auth};});
vi.mock('element-plus',async original=>({...await original(),ElMessage:{success:vi.fn()}}));
import Plan from '../src/components/supply-chain/FreightPlanFieldsV2.vue';
import Channels from '../src/components/supply-chain/FreightChannelsV2.vue';

const stubs={
 'el-form-item':{template:'<label><slot/></label>'},'el-form':{props:['disabled'],template:'<fieldset :disabled="disabled"><slot/></fieldset>'},
 'el-alert':{props:['title'],template:'<p>{{title}}</p>'},
 'el-select':{props:['disabled','modelValue','remoteMethod'],template:'<select :disabled="disabled"><slot/></select>'},
 'el-option':{props:['label','value','disabled'],template:'<option :value="value" :disabled="disabled">{{label}}</option>'},
 'el-button':{props:['disabled','loading'],emits:['click'],template:'<button :disabled="disabled||loading" @click="$emit(\'click\')"><slot/></button>'},
 'el-input':{props:['disabled','modelValue'],template:'<input :disabled="disabled" :value="modelValue"/>'},
 'el-input-number':{template:'<input type="number"/>'},'el-date-picker':{template:'<input/>'},'el-switch':{template:'<input type="checkbox"/>'},
 'el-table':{template:'<div/>'},'el-table-column':{template:'<div/>'},'el-pagination':{template:'<nav/>'},
 'el-dialog':{props:['modelValue'],template:'<div v-if="modelValue"><slot/><slot name="footer"/></div>'},
};
const globals={stubs,directives:{loading:()=>{}}};
const quote={id:22,sequence:2,billing_basis:'cbm',fee_per_cbm:'200.0000',tax_percent:'6.00',prices_include_tax:false};
const channel={id:5,version:3,company_id:9,name:'厦门普货海运',country_id:1,country_code:'PH',origin:'厦门',cargo_type:'普货',code:'XM-PH',transport_mode:'sea',is_active:true,current_quote:null,current_quotes:[quote,{...quote,id:23,sequence:3,fee_per_cbm:'250.0000'}]};
const blank=()=>reactive({freight_company_id:9,freight_channel_id:null,freight_quote_id:null,planned_warehouse_id:null,container_count:1,container_number:'',reason:''});
beforeEach(()=>{mocks.auth.authorizationStale=false;mocks.request.mockReset().mockImplementation(async r=>r.url.endsWith('/options/')?{success:true,data:[{id:1,name:'菲律宾',country_code:'PH'}]}:{success:true,data:[channel],count:1,business_date:'2026-10-15'});});
describe('freight research integration',()=>{
 it('keeps a frozen quote until the buyer explicitly selects a quote from multiple channel options',async()=>{
  const form=blank();Object.assign(form,{freight_channel_id:5,freight_quote_id:21,planned_warehouse_id:12});
  const frozen={...quote,id:21,sequence:1,fee_per_cbm:'100.0000'};
  const w=mount(Plan,{props:{form,countryCode:'PH',warehouses:[{id:12,name:'菲律宾合作仓',country_code:'PH'}],snapshot:{freight_channel_id:5,freight_quote_id:21,freight_quote_snapshot:{name:channel.name,quote:frozen},planned_warehouse_id:12}},global:globals});
  await flushPromises();expect(form.freight_quote_id).toBe(21);expect(w.vm.selectedQuote.fee_per_cbm).toBe('100.0000');
  expect(w.text()).toContain('历史报价（仅沿用）');expect(w.text()).toContain('200.0000 / 方');expect(w.text()).toContain('250.0000 / 方');
  expect(w.text()).not.toContain('采用当前有效报价');expect(w.vm.channels[0].current_quote).toBeNull();w.vm.chooseQuote(23);
  expect(form.freight_quote_id).toBe(23);expect(w.vm.selectedQuote.fee_per_cbm).toBe('250.0000');
  w.unmount();
 });
 it('discards stale channel responses and clears route and plan on a country change',async()=>{
  let resolveOld;mocks.request.mockImplementationOnce(()=>new Promise(resolve=>resolveOld=resolve)).mockResolvedValue({success:true,data:[{...channel,id:7,country_code:'TH'}],count:1});
  const form=blank();Object.assign(form,{freight_channel_id:5,freight_quote_id:22,planned_warehouse_id:12});
  const w=mount(Plan,{props:{form,countryCode:'PH'},global:globals});await w.setProps({countryCode:'TH'});await flushPromises();
  resolveOld({success:true,data:[channel],count:1});await flushPromises();expect(w.vm.channels[0].id).toBe(7);expect(form.freight_channel_id).toBeNull();expect(form.planned_warehouse_id).toBeNull();w.unmount();
 });
 it('supports searching and paging channels and reports malformed data without a render error',async()=>{
  mocks.request.mockResolvedValue({success:true,data:[channel],count:42});const form=blank();const w=mount(Plan,{props:{form,countryCode:'PH'},global:globals});await flushPromises();
  await w.vm.searchChannels('厦门');await flushPromises();w.vm.channelPage=2;await w.vm.loadChannels();
  expect(mocks.request.mock.calls.at(-1)[0].params).toMatchObject({search:'厦门',limit:20,offset:20});
  await w.setProps({disabled:true});w.vm.chooseChannel(5);expect(form.freight_channel_id).toBeNull();
  mocks.request.mockResolvedValue({success:true,data:{}});await w.vm.loadChannels();await flushPromises();expect(w.text()).toContain('渠道读取失败');w.unmount();
 });
 it('publishes a quote with one retry key and suppresses writes after authorization becomes stale',async()=>{
  const writes=[];let fail=true;
  mocks.request.mockImplementation(async r=>{if(r.method==='post'){writes.push(r);if(fail){fail=false;throw new Error('response lost');}return {success:true,data:{...quote,id:23}};}return r.url.endsWith('/options/')?{success:true,data:[]}:{success:true,data:[channel],count:1,business_date:'2026-10-15'};});
  const w=mount(Channels,{props:{company:{id:9,name:'测试货运',is_active:true}},global:globals});await flushPromises();await w.vm.openQuote(channel);
  Object.assign(w.vm.quoteForm,{effective_from:'2026-10-15',fee_per_cbm:'220',reason:'年度报价调整'});await w.vm.publishQuote();await w.vm.publishQuote();
  expect(writes).toHaveLength(2);expect(writes[1].headers['Idempotency-Key']).toBe(writes[0].headers['Idempotency-Key']);expect(writes[0].data).toMatchObject({expected_channel_version:3,fee_per_cbm:'220',container_fee:null});
  mocks.auth.authorizationStale=true;await w.vm.publishQuote();expect(writes).toHaveLength(2);w.unmount();
 });
});
