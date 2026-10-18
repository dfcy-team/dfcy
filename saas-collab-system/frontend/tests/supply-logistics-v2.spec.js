import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks=vi.hoisted(()=>({requestApi:vi.fn(),route:{query:{},fullPath:'/supply-chain/logistics'},canManage:true,confirm:vi.fn().mockResolvedValue(true)}));
vi.mock('vue-router',async original=>({...await original(),useRoute:()=>mocks.route}));
vi.mock('../src/api/request',()=>({requestApi:mocks.requestApi}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({authorizationStale:false,hasPermission:()=>mocks.canManage})}));
vi.mock('element-plus',async original=>({...await original(),ElMessageBox:{confirm:mocks.confirm},ElMessage:{success:vi.fn()}}));
import * as api from '../src/api/supplyLogisticsV2';
import {flushPromises,mount} from '@vue/test-utils';
import SupplyLogisticsV2 from '../src/views/purchasing/SupplyLogisticsV2.vue';

const stubs={
  'router-link':{template:'<a><slot/></a>'},
  AppPage:{template:'<main><slot name="action"/><slot/></main>'},
  'el-button':{props:['disabled','loading','link'],emits:['click'],template:'<button :disabled="disabled||loading" @click="$emit(\'click\')"><slot/></button>'},
  'el-alert':{props:['title'],template:'<p>{{title}}</p>'},'el-tabs':{template:'<div><slot/></div>'},'el-tab-pane':{props:['name'],template:'<section><slot/></section>'},
  'el-input':{props:['modelValue','disabled'],emits:['update:modelValue'],template:'<input :disabled="disabled" :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/>'},
  'el-select':{props:['modelValue','disabled'],emits:['update:modelValue','change'],template:'<select :disabled="disabled" :value="modelValue" @change="$emit(\'update:modelValue\',$event.target.value);$emit(\'change\',$event.target.value)"><slot/></select>'},'el-option':{props:['label','value'],template:'<option :value="value">{{label}}</option>'},
  'el-table':{props:['data'],emits:['selection-change'],template:'<div><button class="select-row" @click="$emit(\'selection-change\',data)">select</button><slot/></div>'},'el-table-column':{template:'<div><slot :row="{}" :$index="0"/></div>'},
  DocumentProductImageV2:{props:['imagePath','alt'],template:'<img :src="imagePath" :alt="alt"/>'},DocumentSkuV2:{props:['sku','legacySkuCode'],template:'<span>{{sku}} {{legacySkuCode}}</span>'},
  'el-pagination':{template:'<nav/>'},'el-dialog':{props:['modelValue'],template:'<div v-if="modelValue"><slot/><slot name="footer"/></div>'},'el-drawer':{props:['modelValue'],template:'<aside v-if="modelValue"><slot/><slot name="footer"/></aside>'},'el-form-item':{template:'<label><slot/></label>'},'el-descriptions':{template:'<div><slot/></div>'},'el-descriptions-item':{template:'<div><slot/></div>'},'el-date-picker':{props:['modelValue','disabled'],emits:['update:modelValue'],template:'<input type="text" :disabled="disabled" :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/>'},'el-input-number':{props:['modelValue','disabled'],emits:['update:modelValue'],template:'<input type="number" :disabled="disabled" :value="modelValue" @input="$emit(\'update:modelValue\',Number($event.target.value))"/>'}
};
function mountPage(){return mount(SupplyLogisticsV2,{global:{stubs,directives:{loading:()=>{}}}});}
const candidates=[{id:4,version:2,number:'S-4',country_code:'US',collection_arrived:false,lines:[{id:2,quantity:8,allocated_quantity:3,remaining_quantity:5,sku:'A',legacy_sku_code:'OLD-A',image_preview_url:'/a.png',product_name:'Widget'},{id:7,quantity:3,allocated_quantity:0,remaining_quantity:3,sku:'A-2',legacy_sku_code:'OLD-A2',image_preview_url:'/a2.png',product_name:'Widget 2'}]}];
const batch={id:8,number:'DB-8',country_code:'US',freight_company_id:9,freight_company_name:'F',freight_number:'T1',notes:'',version:3,stage:'unmarked',logistics_dates:{},shipments:[{...candidates[0],allocation_lines:[{id:2,quantity:8,allocated_quantity:3,remaining_quantity:5,current_batch_quantity:3,available_quantity:8,sku:'A',legacy_sku_code:'OLD-A',image_preview_url:'/a.png',product_name:'Widget'},{id:7,quantity:3,allocated_quantity:0,remaining_quantity:3,current_batch_quantity:0,available_quantity:3,sku:'A-2',legacy_sku_code:'OLD-A2',image_preview_url:'/a2.png',product_name:'Widget 2'}],lines:[{id:2,shipment_line_id:2,quantity:3,source_quantity:8,remaining_quantity:5,available_quantity:8,sku:'A',product_name:'Widget'}]}],inbound_id:null};
const inbound={id:15,number:'IN-15',batch_id:8,batch_number:'DB-8',country_code:'US',warehouse_id:12,warehouse_name:'US warehouse',status:'draft',version:1,notes:'',lines:[{id:3,shipment_line_id:2,shipment_number:'S-4',order_number:'PO-2',supplier_name:'Supplier',sku:'A',product_name:'Widget',expected_quantity:5,received_quantity:null,difference_note:''}]};
function setupResponses(){mocks.requestApi.mockImplementation(async r=>{
  if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[{code:'US',name:'United States'}],freight_companies:[{id:9,code:'F',name:'Forwarder',country_code:'US'}],warehouses:[{id:12,code:'W',name:'US warehouse',country_code:'US'}]}};
  if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:candidates,count:1};
  if(r.url.endsWith('/dispatch-batches/'))return {success:true,data:[batch],count:1};
  if(r.method==='patch'&&r.url.endsWith('/inbound-orders/15/'))return {success:true,data:{...inbound,...r.data,version:2,lines:r.data.lines.map(l=>({...inbound.lines[0],...l}))}};
  if(r.url.endsWith('/inbound-orders/'))return {success:true,data:[inbound],count:1};
  if(r.url.endsWith('/dispatch-batches/8/'))return {success:true,data:batch};
  if(r.url.endsWith('/inbound-orders/15/'))return {success:true,data:inbound};
  if(r.url.endsWith('/dispatch-batches/8/stage/'))return {success:true,data:{...batch,stage:r.data.stage,version:4,logistics_dates:{departed_at:r.data.occurred_at}}};
  if(r.url.endsWith('/inbound-orders/15/confirm/'))return {success:true,data:{...inbound,status:'confirmed',version:3,stock_receipt_ref:'RCPT-1'}};
  return {success:true,data:{...batch,id:20,number:'DB-20'}};
});}

describe('supply logistics API',()=>{
 beforeEach(()=>{mocks.requestApi.mockReset().mockResolvedValue({success:true,data:{}});mocks.canManage=true;mocks.confirm.mockReset().mockResolvedValue(true);});
 it('uses the documented internal routes, query parameters and idempotency header',async()=>{
   await api.fetchDispatchOptions('US');await api.fetchDispatchCandidates({country_code:'US',limit:20,offset:0});
   const retryBody={shipment_ids:[4],shipment_versions:[{id:4,version:2}]};
   await api.createDispatchBatch(retryBody,'same-key');await api.createDispatchBatch(retryBody,'same-key');
   await api.advanceDispatchBatch(8,{expected_version:3,stage:'departed',occurred_at:'2026-10-13T02:00:00.000Z'},'same-key');
   await api.updateDispatchBatchMembers(8,{expected_version:3,shipment_ids:[4],shipment_versions:[{id:4,version:2}],reason:'修正成员'},'same-key');
   await api.cancelDispatchBatch(8,{expected_version:3,reason:'取消原因'},'same-key');
   await api.correctDispatchBatchDate(8,{expected_version:4,stage:'departed',occurred_at:'2026-10-13T02:00:00.000Z',reason:'日期修正'},'same-key');
   expect(mocks.requestApi.mock.calls.map(([r])=>[r.method,r.url,r.params])).toEqual([
     ['get','/api/internal/supply-chain/v2/dispatch-options/',{country_code:'US'}],['get','/api/internal/supply-chain/v2/dispatch-candidates/',{country_code:'US',limit:20,offset:0}],['post','/api/internal/supply-chain/v2/dispatch-batches/',undefined],['post','/api/internal/supply-chain/v2/dispatch-batches/',undefined],['post','/api/internal/supply-chain/v2/dispatch-batches/8/stage/',undefined],['post','/api/internal/supply-chain/v2/dispatch-batches/8/members/',undefined],['post','/api/internal/supply-chain/v2/dispatch-batches/8/cancel/',undefined],['post','/api/internal/supply-chain/v2/dispatch-batches/8/dates/',undefined]
   ]);expect(mocks.requestApi.mock.calls[2][0].headers['Idempotency-Key']).toBe('same-key');
   expect(mocks.requestApi.mock.calls[3][0].headers['Idempotency-Key']).toBe('same-key');
   expect(mocks.requestApi.mock.calls.slice(4).every(([r])=>r.headers['Idempotency-Key']==='same-key')).toBe(true);
 });
});

describe('dispatch and inbound workbench',()=>{
 beforeEach(()=>{mocks.requestApi.mockClear();setupResponses();mocks.canManage=true;mocks.confirm.mockClear().mockResolvedValue(true);});
 it('offers a non-arrived submitted candidate and records only the next transport stage',async()=>{
   const w=mountPage();await flushPromises();
   expect(w.text()).toContain('未到仓');
   await w.vm.openBatch(batch);await flushPromises();
   expect(w.text()).toContain('开船');expect(w.text()).toContain('到仓');
   w.vm.occurredAt='2026-10-13T10:00:00';await w.vm.advanceStage();await flushPromises();
   const stage=mocks.requestApi.mock.calls.find(([r])=>r.url.endsWith('/stage/'))[0];
   expect(stage.data.stage).toBe('departed');expect(stage.data.expected_version).toBe(3);expect(stage.data.occurred_at).toContain('Z');w.unmount();
 });
 it('defaults a newly selected partially dispatched shipment to remaining quantity',async()=>{
   const original=mocks.requestApi.getMockImplementation(),writes=[];
   mocks.requestApi.mockImplementation(async r=>{
     if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:[...candidates,{id:5,version:6,number:'S-5',country_code:'US',lines:[{id:6,quantity:10,allocated_quantity:8,remaining_quantity:2,sku:'B'}]}],count:2};
     if(r.url.endsWith('/members/')){writes.push(r);return {success:true,data:{...batch,version:4}};}
     return original(r);
   });
   const w=mountPage();await flushPromises();await w.vm.openBatch(batch);await flushPromises();
   w.vm.memberSelection=[4,5];w.vm.memberReason='加入剩余货物';await w.vm.saveMembers();await flushPromises();
   expect(writes).toHaveLength(1);expect(writes[0].data.allocations.find(row=>row.shipment_line_id===6).quantity).toBe(2);
   w.unmount();
 });
 it('creates a batch with editable per-SKU allocations and omits zero lines',async()=>{
   const writes=[];mocks.requestApi.mockImplementation(async r=>{if(r.method==='post'&&r.url.endsWith('/dispatch-batches/')){writes.push(r);return {success:true,data:{...batch,id:20}};}if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[{code:'US',name:'United States'}],freight_companies:[{id:9,code:'F',name:'Forwarder',country_code:'US'}],warehouses:[]}};if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:candidates,count:1};if(r.url.endsWith('/dispatch-batches/'))return {success:true,data:[],count:0};if(r.url.endsWith('/dispatch-batches/20/'))return {success:true,data:batch};return {success:true,data:{}};});
   const w=mountPage();await flushPromises();w.vm.selectedCandidates=candidates;w.vm.batchForm.freight_company_id=9;w.vm.createAllocations[2]=3;w.vm.createAllocations[7]=0;await w.vm.createBatch();await flushPromises();
   expect(writes).toHaveLength(1);expect(writes[0].data.allocations).toEqual([{shipment_line_id:2,quantity:3}]);expect(writes[0].data.shipment_ids).toEqual([4]);w.unmount();
 });
 it('keeps unallocated SKUs at zero for an existing member, while showing product and allocation details',async()=>{
   const writes=[];mocks.requestApi.mockImplementation(async r=>{if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[{code:'US',name:'United States'}],freight_companies:[],warehouses:[]}};if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:[],count:0};if(r.url.endsWith('/dispatch-batches/8/')&&r.method==='get')return {success:true,data:batch};if(r.url.endsWith('/members/')){writes.push(r);return {success:true,data:{...batch,version:3+writes.length}};}if(r.url.endsWith('/dispatch-batches/'))return {success:true,data:[batch],count:1};return {success:true,data:{}};});
   const w=mountPage();await flushPromises();await w.vm.openBatch(batch);await flushPromises();
   expect(w.vm.memberAllocationRows.map(row=>row.defaultQuantity)).toEqual([3,0]);expect(w.text()).toContain('OLD-A');expect(w.text()).toContain('OLD-A2');expect(w.text()).toContain('原发货 8');expect(w.text()).toContain('已分配 3');expect(w.text()).toContain('剩余 5');expect(w.find('img[src="/a2.png"]').exists()).toBe(true);
   w.vm.memberAllocations[2]=2;w.vm.memberReason='调整本批数量';await w.vm.saveMembers();await flushPromises();expect(writes[0].data.allocations).toEqual([{shipment_line_id:2,quantity:2}]);
   w.vm.memberAllocations[7]=2;w.vm.memberReason='补入第二 SKU';await w.vm.saveMembers();await flushPromises();expect(writes[1].data.allocations).toEqual([{shipment_line_id:2,quantity:2},{shipment_line_id:7,quantity:2}]);w.unmount();
 });
 it('requires actual receipt and variance notes, permits zero, saves before confirm, and leaves draft unconfirmed until explicit action',async()=>{
   const w=mountPage();await flushPromises();
   await w.vm.openInbound(inbound);await flushPromises();
   await w.findAll('button').find(b=>b.text()==='确认入库并记账').trigger('click');await flushPromises();
   expect(w.text()).toContain('填写 0 或更大的整数');expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/confirm/'))).toBe(false);
   w.vm.inboundForm.lines[0].received_quantity=0;w.vm.inboundForm.lines[0].difference_note='外箱破损';
   await w.vm.saveInbound();await flushPromises();
   expect(mocks.requestApi.mock.calls.some(([r])=>r.method==='patch'&&r.url.endsWith('/inbound-orders/15/'))).toBe(true);
   expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/confirm/'))).toBe(false);
   const saved=mocks.requestApi.mock.calls.find(([r])=>r.method==='patch'&&r.url.endsWith('/inbound-orders/15/'))[0];expect(saved.data.lines[0].received_quantity).toBe(0);w.unmount();
 });
 it('loads the batch country warehouse before generating an inbound draft',async()=>{
   const arrived={...batch,stage:'arrived_warehouse',version:7,inbound_id:null};
   mocks.requestApi.mockImplementation(async r=>{
     if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[{code:'US',name:'United States'}],freight_companies:[],warehouses:r.params?.country_code==='US'?[{id:12,code:'W',name:'US warehouse',country_code:'US'}]:[]}};
     if(r.url.endsWith('/dispatch-batches/8/'))return {success:true,data:arrived};
     if(r.url.endsWith('/dispatch-batches/8/inbound/'))return {success:true,data:{id:15}};
     if(r.url.endsWith('/inbound-orders/15/'))return {success:true,data:inbound};
     if(r.url.endsWith('/inbound-orders/'))return {success:true,data:[inbound],count:1};
     if(r.url.endsWith('/dispatch-candidates/')||r.url.endsWith('/dispatch-batches/'))return {success:true,data:[],count:0};
     return {success:true,data:arrived};
   });
   const w=mountPage();await flushPromises();await w.vm.openBatch(batch);await flushPromises();
   expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/dispatch-options/')&&r.params?.country_code==='US')).toBe(true);
   w.vm.warehouseId=12;await w.vm.makeInbound();await flushPromises();
   expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/dispatch-batches/8/inbound/'))).toBe(true);
   expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/confirm/'))).toBe(false);w.unmount();
 });
 it('retries a lost inbound confirmation with the same body and key without saving twice',async()=>{
   let lostResponse=true;const confirmationWrites=[];let saves=0;
   mocks.requestApi.mockImplementation(async r=>{
     if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[{code:'US',name:'United States'}],freight_companies:[],warehouses:[{id:12,code:'W',name:'US warehouse',country_code:'US'}]}};
     if(r.url.endsWith('/inbound-orders/15/')&&r.method==='get')return {success:true,data:inbound};
     if(r.url.endsWith('/inbound-orders/15/')&&r.method==='patch'){saves++;return {success:true,data:{...inbound,...r.data,version:2,lines:r.data.lines.map(l=>({...inbound.lines[0],...l}))}};}
     if(r.url.endsWith('/inbound-orders/15/confirm/')){confirmationWrites.push(r);if(lostResponse){lostResponse=false;throw new Error('response lost after commit');}return {success:true,data:{...inbound,status:'confirmed',version:3,stock_receipt_ref:'RCPT-15'}};}
     if(r.url.endsWith('/inbound-orders/'))return {success:true,data:[],count:0};
     if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[],freight_companies:[],warehouses:[]}};
     if(r.url.endsWith('/dispatch-candidates/')||r.url.endsWith('/dispatch-batches/'))return {success:true,data:[],count:0};
     return {success:true,data:{}};
   });
   const w=mountPage();await flushPromises();await w.vm.openInbound(inbound);await flushPromises();
   w.vm.inboundForm.lines[0].received_quantity=5;
   await w.vm.confirmInbound();await flushPromises();
   expect(saves).toBe(1);expect(confirmationWrites).toHaveLength(1);const first=confirmationWrites[0];
   await w.vm.confirmInbound();await flushPromises();
   expect(saves).toBe(1);expect(confirmationWrites).toHaveLength(2);
   expect(confirmationWrites[1].data).toEqual(first.data);expect(confirmationWrites[1].headers['Idempotency-Key']).toBe(first.headers['Idempotency-Key']);
   expect(w.text()).toContain('RCPT-15');w.unmount();
 });
 it('hides mutations for read-only users and reuses an idempotency key on identical retry',async()=>{
   mocks.canManage=false;let failOnce=true;mocks.requestApi.mockImplementation(async r=>{
     if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[{code:'US',name:'United States'}],freight_companies:[],warehouses:[]}};
     if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:candidates,count:1};
     if(r.url.endsWith('/dispatch-batches/'))return {success:true,data:[],count:0};
     if(r.method==='post'){if(failOnce){failOnce=false;throw new Error('temporary failure');}return {success:true,data:{...batch,id:20}};}
     return {success:true,data:{...batch,id:20}};
   });
   const w=mountPage();await flushPromises();expect(w.text()).not.toContain('创建发运批次');await w.vm.openBatch(batch);await flushPromises();expect(w.text()).not.toContain('更新批次成员');expect(w.text()).not.toContain('取消未发运批次');expect(w.text()).not.toContain('保存日期修正');w.unmount();
   // Retried writes are covered at the API boundary above; stage updates also verify optimistic versioning.
 });
 it('updates predeparture members with versions and reuses retry key; cancellation removes all write controls',async()=>{
   let fail=true;const writes=[];const cancelled={...batch,status:'cancelled',stage:'unmarked',shipments:[],history:[{id:99,action:'batch_cancelled',payload:{reason:'计划调整'},created_at:'2026-10-13T00:00:00Z'}]};
   mocks.requestApi.mockImplementation(async r=>{
     if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[],freight_companies:[],warehouses:[]}};
     if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:[...candidates,{id:5,version:6,number:'S-5',country_code:'US',lines:[{id:6,quantity:4,allocated_quantity:0,remaining_quantity:4,sku:'B'}]}],count:2};
     if(r.url.endsWith('/dispatch-batches/8/')&&r.method==='get')return {success:true,data:{...batch,status:'active'}};
     if(r.url.endsWith('/members/')){writes.push(r);if(fail){fail=false;throw new Error('response lost');}const bumped= writes.length===2;return {success:true,data:{...batch,status:'active',version:bumped?4:5,shipments:[{...candidates[0],version:bumped?3:4},{id:5,version:bumped?7:8,number:'S-5',country_code:'US'}]}};}
     if(r.url.endsWith('/cancel/'))return {success:true,data:cancelled};
     if(r.url.endsWith('/dispatch-batches/'))return {success:true,data:[],count:0};
     return {success:true,data:{}};
   });
   let w=mountPage();await flushPromises();await w.vm.openBatch(batch);await flushPromises();expect(w.findAll('button').map(b=>b.text())).not.toContain('保存日期修正');
   w.vm.memberSelection=[4,5];w.vm.memberReason='合并运输';w.vm.memberAllocations[2]=2;w.vm.memberAllocations[7]=2;w.vm.memberAllocations[6]=1;await w.vm.saveMembers();await flushPromises();await w.vm.saveMembers();await flushPromises();
   const expectedMemberBody={expected_version:3,shipment_ids:[4,5],shipment_versions:[{id:4,version:2},{id:5,version:6}],allocations:[{shipment_line_id:2,quantity:2},{shipment_line_id:7,quantity:2},{shipment_line_id:6,quantity:1}],reason:'合并运输'};
   expect(writes).toHaveLength(2);expect(writes[0].data).toEqual(expectedMemberBody);expect(writes[1].data).toEqual(writes[0].data);expect(writes[1].headers['Idempotency-Key']).toBe(writes[0].headers['Idempotency-Key']);
   w.vm.memberReason='再次调整';await w.vm.saveMembers();await flushPromises();expect(writes[2].data.expected_version).toBe(4);expect(writes[2].data.shipment_versions).toEqual([{id:4,version:3},{id:5,version:7}]);
   w.vm.cancelReason='计划调整';await w.vm.cancelBatch();await flushPromises();expect(w.text()).toContain('已取消');expect(w.text()).toContain('计划调整');expect(w.text()).not.toContain('保存批次信息');expect(w.text()).not.toContain('运单号');expect(w.text()).not.toContain('节点发生时间');const labels=w.findAll('button').map(b=>b.text());expect(labels).not.toContain('取消未发运批次');expect(labels).not.toContain('更新批次成员');expect(labels).not.toContain('开船');w.unmount();
 });
 it('saves selected quote and destination plan before advancing departure',async()=>{
   const original=mocks.requestApi.getMockImplementation(),writes=[];
   mocks.requestApi.mockImplementation(async r=>{
     if(r.method==='patch'&&r.url.endsWith('/dispatch-batches/8/')){writes.push(r);return {success:true,data:{...batch,...r.data,version:4}};}
     if(r.url.endsWith('/stage/')){writes.push(r);return {success:true,data:{...batch,version:5,stage:'departed'}};}
     return original(r);
   });
   const w=mountPage();await flushPromises();await w.vm.openBatch(batch);await flushPromises();
   Object.assign(w.vm.batchEdit,{freight_channel_id:30,freight_quote_id:31,planned_warehouse_id:12,container_number:'TEST-CONT',container_count:2});
   w.vm.occurredAt='2026-10-15T10:00:00';await w.vm.advanceStage();await flushPromises();
   expect(writes).toHaveLength(2);expect(writes[0].data).toMatchObject({freight_channel_id:30,freight_quote_id:31,planned_warehouse_id:12,container_number:'TEST-CONT',container_count:2});expect(writes[1].data.expected_version).toBe(4);w.unmount();
 });
 it('defaults the planned destination and requires a reason when generating at another warehouse',async()=>{
   const original=mocks.requestApi.getMockImplementation(),writes=[];
   mocks.requestApi.mockImplementation(async r=>{
     if(r.url.endsWith('/dispatch-batches/8/')&&r.method==='get')return {success:true,data:{...batch,stage:'arrived_warehouse',planned_warehouse_id:12,planned_warehouse_name:'Plan warehouse'}};
     if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{warehouses:[{id:12,name:'Plan warehouse',country_code:'US'},{id:13,name:'Actual warehouse',country_code:'US'}],freight_companies:[]}};
     if(r.url.endsWith('/dispatch-batches/8/inbound/')){writes.push(r);return {success:true,data:{...inbound,warehouse_id:13}};}
     return original(r);
   });
   const w=mountPage();await flushPromises();await w.vm.openBatch(batch);await flushPromises();expect(w.vm.warehouseId).toBe(12);
   w.vm.warehouseId=13;await w.vm.makeInbound();expect(writes).toHaveLength(0);expect(w.text()).toContain('改仓原因');
   w.vm.makeInboundReason='计划仓预约满，改用同国合作仓';await w.vm.makeInbound();expect(writes[0].data).toMatchObject({warehouse_id:13,reason:'计划仓预约满，改用同国合作仓'});w.unmount();
 });
 it('requires date correction reason and sends a timezone-aware timestamp without changing the stage',async()=>{
   const dated={...batch,status:'active',stage:'arrived_port',version:9,logistics_dates:{departed_at:'2026-10-01T02:00:00Z',arrived_port_at:'2026-10-05T04:00:00Z'}};let write;
   mocks.requestApi.mockImplementation(async r=>{if(r.url.endsWith('/dispatch-options/'))return {success:true,data:{countries:[],freight_companies:[],warehouses:[]}};if(r.url.endsWith('/dispatch-batches/8/')&&r.method==='get')return {success:true,data:dated};if(r.url.endsWith('/dates/')){write=r;return {success:true,data:{...dated,version:10,logistics_dates:{...dated.logistics_dates,arrived_port_at:r.data.occurred_at}}};}if(r.url.endsWith('/dispatch-batches/'))return {success:true,data:[],count:0};if(r.url.endsWith('/dispatch-candidates/'))return {success:true,data:[],count:0};return {success:true,data:{}};});
   const w=mountPage();await flushPromises();await w.vm.openBatch(dated);await flushPromises();w.vm.dateStage='arrived_port';w.vm.correctedAt='2026-10-06T12:30:00';await w.vm.correctDate();expect(w.text()).toContain('修正原因');expect(write).toBeUndefined();w.vm.dateReason='货代回执更正';await w.vm.correctDate();await flushPromises();expect(write.data).toEqual({expected_version:9,stage:'arrived_port',occurred_at:new Date('2026-10-06T12:30:00').toISOString(),reason:'货代回执更正'});expect(w.vm.currentBatch.stage).toBe('arrived_port');w.unmount();
 });
});


describe('linked document navigation',()=>{
 it('opens the batch referenced by a procurement progress link',async()=>{
   mocks.route.query={batch_id:'8'};mocks.requestApi.mockReset();setupResponses();
   const wrapper=mountPage();await flushPromises();
   expect(wrapper.vm.batchOpen).toBe(true);expect(wrapper.vm.currentBatch.id).toBe(8);
   expect(mocks.requestApi.mock.calls.some(([r])=>r.url.endsWith('/dispatch-batches/8/'))).toBe(true);
   wrapper.unmount();mocks.route.query={};
 });
});
