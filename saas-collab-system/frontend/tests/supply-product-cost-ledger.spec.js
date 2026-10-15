import {beforeEach,describe,expect,it,vi} from 'vitest';
import {computed,defineComponent,h,inject,nextTick,provide,reactive} from 'vue';
import {flushPromises,mount} from '@vue/test-utils';

const mocks=vi.hoisted(()=>({requestApi:vi.fn(),authState:null}));
vi.mock('../src/api/request',()=>({requestApi:mocks.requestApi}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({get authorizationStale(){return mocks.authState.authorizationStale;},hasPermission:()=>mocks.authState.permitted})}));

import ProductCostLedgerV2 from '../src/components/supply-chain/ProductCostLedgerV2.vue';

const row={id:9,sku_id:41,sku:'SKU-41',product_name:'Widget',country_id:3,country_code:'US',warehouse_id:7,warehouse_name:'West',batch_id:12,batch_number:'B-12',shipment_number:'S-8',quantity:2,received_quantity:null,shipped_unit_cost:null,received_unit_cost:0,status:'recalculation_required',sequence:4,is_latest:true,goods_amount:null,collection_fee:0,freight_fee:null,clearance_fee:null,shipped_total:null,received_goods_amount:null,received_collection_fee:null,received_freight_fee:null,received_total:null,pending_total:null};
const optionData={countries:[{id:3,name:'United States',country_code:'US'}],warehouses:[{id:7,name:'West',country_code:'US'}],batches:[{id:12,name:'Batch 12'}]};

const stubs={
 'el-alert':{props:['title'],template:'<p role="alert">{{title}}</p>'},
 'el-form-item':{props:['label'],template:'<label>{{label}}<slot/></label>'},
 'el-input':{props:['modelValue','placeholder'],emits:['update:modelValue','input'],template:'<input :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value);$emit(\'input\',$event.target.value)" />'},
 'el-select':{props:['modelValue'],emits:['update:modelValue'],template:'<select :value="modelValue" @change="$emit(\'update:modelValue\',$event.target.value)"><slot/></select>'},
 'el-option':{props:['label','value'],template:'<option :value="value">{{label}}</option>'},
 'el-button':{props:['disabled'],emits:['click'],template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot/></button>'},
 'el-table':defineComponent({props:['data'],setup(props,{slots}){provide('ledgerRows',computed(()=>props.data));return()=>h('div',{class:'table-stub'},slots.default?.());}}),
 'el-table-column':defineComponent({props:['label','prop'],setup(props,{slots}){const rows=inject('ledgerRows');return()=>h('div',{class:'column-stub'},[props.label,...rows.value.map(item=>props.prop?h('span',String(item[props.prop]??'')):slots.default?.({row:item}))]);}}),
 'el-pagination':{props:['currentPage','total'],emits:['current-change'],template:'<div><button @click="$emit(\'current-change\', currentPage+1)">下一页</button></div>'},
 'el-drawer':{props:['modelValue','title'],template:'<aside v-if="modelValue"><h2>{{title}}</h2><slot/></aside>'},
 'el-descriptions':{template:'<div><slot/></div>'},
 'el-descriptions-item':{props:['label'],template:'<p>{{label}}：<slot/></p>'},
};

function mountLedger(){return mount(ProductCostLedgerV2,{global:{stubs,directives:{loading:()=>{}}}});}
function responseFor(config){
 if(config.url.endsWith('/options/')){const kind=config.params.kind;return {success:true,data:optionData[kind]||[]};}
 return {success:true,data:[row],count:27};
}

describe('ProductCostLedgerV2 query ledger',()=>{
 beforeEach(()=>{
  mocks.authState=reactive({authorizationStale:false,permitted:true});
  mocks.requestApi.mockReset().mockImplementation(async config=>responseFor(config));
 });

 it('keeps all selected filters when moving to the next result page',async()=>{
  const wrapper=mountLedger();await flushPromises();
  await wrapper.find('input[placeholder="SKU 或商品名称"]').setValue('SKU-41');
  const selects=wrapper.findAll('select');
  await selects[0].setValue('3');await selects[1].setValue('7');await selects[2].setValue('12');
  await selects[3].setValue('all');
  await wrapper.get('button').trigger('click');
  const first=mocks.requestApi.mock.calls.filter(([config])=>config.url.endsWith('/product-cost-ledger/')).at(-1)[0].params;
  expect(first).toMatchObject({search:'SKU-41',country_id:'3',warehouse_id:'7',batch_id:'12',versions:'all',limit:20,offset:0});
  await wrapper.findAll('button').find(button=>button.text()==='下一页').trigger('click');
  const second=mocks.requestApi.mock.calls.filter(([config])=>config.url.endsWith('/product-cost-ledger/')).at(-1)[0].params;
  expect(second).toMatchObject({search:'SKU-41',country_id:'3',warehouse_id:'7',batch_id:'12',versions:'all',limit:20,offset:20});
 });

 it('shows pending recalculation and preserves null versus numeric zero costs',async()=>{
  const wrapper=mountLedger();await flushPromises();
  expect(wrapper.text()).toContain('待复算');
  expect(wrapper.text()).toContain('未确定');
  wrapper.vm.detail=row;await nextTick();
  expect(wrapper.text()).toContain('发货货值：未确定');
  expect(wrapper.text()).toContain('到集货点费用：0');
 });

 it('switches a row into all-history mode while locking its SKU and country',async()=>{
  const wrapper=mountLedger();await flushPromises();
  const historyButton=wrapper.findAll('button').find(button=>button.text()==='历史版本');
  expect(historyButton).toBeTruthy();await historyButton.trigger('click');
  const request=mocks.requestApi.mock.calls.filter(([config])=>config.url.endsWith('/product-cost-ledger/')).at(-1)[0].params;
  expect(request).toMatchObject({sku_id:41,search:'SKU-41',country_id:3,versions:'all',limit:20,offset:0});
  expect(wrapper.vm.draft.warehouse_id).toBe('');expect(wrapper.vm.draft.batch_id).toBe('');
 });

 it('ignores a slower earlier query after newer filters are submitted',async()=>{
  let resolveOld;
  mocks.requestApi.mockImplementation(config=>{
   if(config.url.endsWith('/options/'))return Promise.resolve({success:true,data:[]});
   if(config.params.search==='old')return new Promise(resolve=>{resolveOld=resolve;});
   return Promise.resolve({success:true,data:[{...row,sku:'NEW'}],count:1});
  });
  const wrapper=mountLedger();await flushPromises();
  wrapper.vm.draft.search='old';const oldQuery=wrapper.vm.search();
  wrapper.vm.draft.search='new';await wrapper.vm.search();
  resolveOld({success:true,data:[{...row,sku:'OLD'}],count:1});await oldQuery;await flushPromises();
  expect(wrapper.text()).toContain('NEW');expect(wrapper.text()).not.toContain('OLD');
 });

 it('clears already loaded rows when authorization becomes stale',async()=>{
  const wrapper=mountLedger();await flushPromises();
  expect(wrapper.text()).toContain('SKU-41');
  mocks.authState.authorizationStale=true;await nextTick();await nextTick();
  expect(wrapper.text()).toContain('需要供应链查看权限及对应数据范围。');
  expect(wrapper.text()).not.toContain('SKU-41');
  expect(wrapper.vm.rows).toEqual([]);expect(wrapper.vm.total).toBe(0);
 });
});
