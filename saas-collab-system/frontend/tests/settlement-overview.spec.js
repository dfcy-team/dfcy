import {beforeEach,describe,expect,it,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
const m=vi.hoisted(()=>({fetch:vi.fn(),queue:vi.fn()}));
vi.mock('../src/api/supplyDashboardV2',()=>({fetchDashboard:m.fetch,fetchDashboardQueue:m.queue}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:1},authorizationStale:false})}));
import Overview from '../src/components/supply-chain/SettlementOverviewV2.vue';
const overview={groups:{supplier:{amount:'100',paid:'30',opening:'10',applied:'20',unsettled:'50',ranking:[]}}};
const mountPanel=()=>mount(Overview,{props:{overview,countryId:3},global:{stubs:{'el-select':true,'el-input':true,'el-button':true,'el-table':true,'el-pagination':true,'el-alert':true},directives:{loading:{}}}});
describe('结算跨单据穿透',()=>{
 beforeEach(()=>{m.fetch.mockReset();m.queue.mockReset().mockResolvedValue({success:true,data:[{id:1,kind:'shipment'}],count:1});});
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
