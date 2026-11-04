import {beforeEach,describe,expect,it,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import {ElPagination} from 'element-plus';
const m=vi.hoisted(()=>({fetch:vi.fn(),queue:vi.fn(),push:vi.fn()}));
vi.mock('vue-router',()=>({useRouter:()=>({push:m.push}),useRoute:()=>({fullPath:'/',query:{}})}));
vi.mock('../src/api/supplyDashboardV2',()=>({fetchDashboard:m.fetch,fetchDashboardQueue:m.queue}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:1},authorizationStale:false})}));
import Overview from '../src/components/supply-chain/SettlementOverviewV2.vue';
const overview={groups:{supplier:{amount:'100',purchase_total_amount:'120',shipment_total_amount:'80',cash_paid_amount:'35',purchase_paid_amount:'25',direct_paid_amount:'10',opening:'10',applied:'20',payable_amount:'145',unsettled:'50',ranking:[]},domestic:{amount:'70',cash_paid_amount:'20',opening:'5',unsettled:'50',ranking:[]},carrier:{amount:'60',cash_paid_amount:'15',opening:'0',unsettled:'45',ranking:[]},clearance:{amount:'40',cash_paid_amount:'10',opening:'0',unsettled:'30',ranking:[]},deposit:{amount:'30',cash_paid_amount:'12',opening:'2',applied:'8',unsettled:'18',available_prepayment:'4',ranking:[]}}};
const mountPanel=()=>mount(Overview,{props:{overview,countryId:3},global:{stubs:{'el-select':true,'el-input':true,'el-button':true,'el-table':true,'el-pagination':true,'el-alert':true},directives:{loading:{}}}});
describe('结算跨单据穿透',()=>{
 beforeEach(()=>{m.fetch.mockReset();m.queue.mockReset().mockResolvedValue({success:true,data:[{id:1,kind:'shipment'}],count:1});});
 it('keeps the actual pager on the selected page while loading and resets on filter change',async()=>{
  m.queue.mockResolvedValue({success:true,data:[{id:1,kind:'shipment'}],count:60});
  const w=mount(Overview,{props:{overview,countryId:3},global:{components:{ElPagination},stubs:{PaymentRemindersV2:true,MonthlyPayablesV2:true,'el-select':true,'el-input':true,'el-button':true,'el-table':true,'el-alert':true},directives:{loading:{}}}});
  await w.vm.openGroup('supplier');await flushPromises();let resolve;m.queue.mockReturnValueOnce(new Promise(r=>resolve=r));
  await w.find('.el-pager li[aria-label="page 2"]').trigger('click');await flushPromises();
  expect(w.findComponent(ElPagination).props('currentPage')).toBe(2);expect(m.queue).toHaveBeenCalledTimes(2);expect(m.queue.mock.lastCall[0].offset).toBe(20);
  resolve({success:true,data:[{id:21,kind:'shipment'}],count:60});await flushPromises();
  await w.find('.el-pager li[aria-label="page 3"]').trigger('click');await flushPromises();expect(m.queue.mock.lastCall[0].offset).toBe(40);expect(w.findComponent(ElPagination).props('currentPage')).toBe(3);
  w.vm.status='settled';await w.vm.resetList();await flushPromises();expect(m.queue.mock.lastCall[0].offset).toBe(0);expect(w.findComponent(ElPagination).props('currentPage')).toBe(1);w.unmount();
 });
 it('uses provided totals without eager list calls',async()=>{const w=mountPanel();await flushPromises();expect(m.fetch).not.toHaveBeenCalled();expect(m.queue).not.toHaveBeenCalled();expect(w.text()).toContain('定金抵扣');w.unmount();});
 it('opens all documents for a country and party, including settled',async()=>{const w=mountPanel();await w.vm.openGroup('supplier',{id:8,name:'供应商'});expect(m.queue).toHaveBeenCalledWith({queue:'supplier',status:'all',search:'',limit:20,offset:0,country_id:3,party_id:8});expect(w.vm.rows).toHaveLength(1);w.unmount();});
 it('clears supplier filter when changing to carriers',async()=>{const w=mountPanel();await w.vm.openGroup('supplier',{id:8});w.vm.queue='carrier';await w.vm.changeKind();expect(m.queue.mock.lastCall[0].party_id).toBeUndefined();expect(m.queue.mock.lastCall[0].queue).toBe('carrier');w.unmount();});
 it('passes settled status explicitly',async()=>{const w=mountPanel();await w.vm.openGroup('domestic');w.vm.status='settled';await w.vm.resetList();expect(m.queue.mock.lastCall[0].status).toBe('settled');w.unmount();});
 it('does not show an old country response after switching',async()=>{let resolve;m.queue.mockReturnValueOnce(new Promise(r=>resolve=r));const w=mountPanel();const pending=w.vm.openGroup('deposit');await w.setProps({countryId:4});resolve({success:true,data:[{id:999}],count:1});await pending;expect(w.vm.rows).toEqual([]);w.unmount();});
});

it('passes actual nature and paid project filters and clears them on category change',async()=>{
 const w=mountPanel();await w.vm.openGroup('clearance');w.vm.paymentNature='mixed';w.vm.paymentItem='清关费';await w.vm.resetList();
 expect(m.queue.mock.lastCall[0]).toMatchObject({queue:'clearance',payment_nature:'mixed',payment_item:'清关费'});
 w.vm.queue='supplier';await w.vm.changeKind();expect(m.queue.mock.lastCall[0].payment_nature).toBeUndefined();expect(m.queue.mock.lastCall[0].payment_item).toBeUndefined();w.unmount();
});

it('filters never-paid items and clears status when changing category',async()=>{const w=mountPanel();await w.vm.openGroup('carrier');w.vm.itemStatus='unpaid';w.vm.paymentItem='海运费';await w.vm.resetList();expect(m.queue.mock.lastCall[0]).toMatchObject({item_status:'unpaid',payment_item:'海运费',offset:0});w.vm.queue='supplier';await w.vm.changeKind();expect(m.queue.mock.lastCall[0].item_status).toBeUndefined();w.unmount();});

it('routes cockpit supplier and freight payment entries to reconciliation',()=>{const w=mountPanel();w.vm.goPay('supplier',8,'供方');expect(m.push).toHaveBeenLastCalledWith({path:'/supply-chain/costs',query:{tab:'reconciliation',party_kind:'supplier',party_id:8,party_name:'供方'}});w.vm.goPay('carrier',9,'货运方');expect(m.push.mock.lastCall[0].query.party_kind).toBe('freight_company');w.unmount();});


it('shows totals and actual cash before remaining, without adding deposit offsets to paid cash',()=>{
 const w=mountPanel();const text=w.text();
 for(const label of ['总采购金额','总发货金额','总国内运费','总批次货运费','总入库清关费','已付款金额','剩余应付','可用余额'])expect(text).toContain(label);
 expect(text).toContain('145.00'); // supplier uses backend payable_amount
 expect(text).toContain('35.00'); // actual cash already includes supplier purchase deposits; applied is separate
 expect(text).toContain('8.00'); // deposit applied remains visible separately
 expect(text.indexOf('总采购金额')).toBeLessThan(text.indexOf('已付款金额'));
 expect(text.indexOf('已付款金额')).toBeLessThan(text.indexOf('剩余应付'));
 w.unmount();
});
