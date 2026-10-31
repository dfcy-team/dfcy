import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks=vi.hoisted(()=>({fetchDashboard:vi.fn(),fetchDashboardQueue:vi.fn(),push:vi.fn()}));
vi.mock('../src/api/supplyDashboardV2',()=>mocks);
vi.mock('vue-router',()=>({useRouter:()=>({push:mocks.push}),useRoute:()=>({query:{}})}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({authorizationStale:false,hasPermission:()=>false,hasMenuPermission:()=>false})}));
import Dashboard from '../src/views/purchasing/SupplyDashboardV2.vue';
const data={totals:{unshipped_quantity:5},countries:[],country_options:[{id:1,name:'USA',country_code:'US'}],generated_at:'2026-10-21T00:00:00Z',notices:[]};
const response=d=>({success:true,data:d});
const stubs={AppPage:{template:'<main><slot/></main>'},CountryFlagV2:true,'el-select':true,'el-option':true,'el-button':true,'el-alert':true,'el-tabs':{template:'<div><slot/></div>'},'el-tab-pane':{template:'<div><slot/></div>'},'el-table':true,'el-table-column':true,'el-drawer':true,'el-pagination':true};
const create=()=>mount(Dashboard,{global:{stubs,directives:{loading:()=>{}}}});
describe('supply dashboard',()=>{
 beforeEach(()=>{mocks.fetchDashboard.mockReset().mockResolvedValue(response(data));mocks.fetchDashboardQueue.mockReset();});
 it('loads operations only, lazily loads costs and forwards country and bounded queue pagination',async()=>{
  const w=create();await flushPromises();expect(mocks.fetchDashboard).toHaveBeenCalledTimes(1);expect(mocks.fetchDashboard.mock.lastCall[0]).toEqual({section:'operations'});
  w.vm.countryId=1;await w.vm.changeCountry();expect(mocks.fetchDashboard.mock.lastCall[0].country_id).toBe(1);
  mocks.fetchDashboard.mockResolvedValue(response({...data,groups:{supplier:{ranking:[]},carrier:{ranking:[]}}}));w.vm.section='costs';await w.vm.changeSection();expect(mocks.fetchDashboard.mock.lastCall[0].section).toBe('costs');
  mocks.fetchDashboard.mockResolvedValue(response({...data,status:'unavailable',totals:{available_quantity:null},notice:'缺少库存权限'}));w.vm.section='inventory';await w.vm.changeSection();expect(mocks.fetchDashboard.mock.lastCall[0].section).toBe('inventory');expect(w.vm.inventory.totals.available_quantity).toBeNull();
  mocks.fetchDashboardQueue.mockResolvedValue({success:true,data:[{number:'PO'}],count:1});await w.vm.openQueue('purchases','待发货');expect(mocks.fetchDashboardQueue.mock.lastCall[0]).toEqual({queue:'purchases',limit:20,offset:0,country_id:1});expect(w.vm.queueRows).toHaveLength(1);w.unmount();
 });
 it('discards an old country response when country changes again',async()=>{
  const w=create();await flushPromises();let finish;mocks.fetchDashboard.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));w.vm.countryId=1;const pending=w.vm.changeCountry();mocks.fetchDashboard.mockResolvedValue(response({...data,totals:{unshipped_quantity:9}}));w.vm.countryId=2;await w.vm.changeCountry();finish(response({...data,totals:{unshipped_quantity:99}}));await pending;expect(w.vm.operations.totals.unshipped_quantity).toBe(9);w.unmount();
 });
});
