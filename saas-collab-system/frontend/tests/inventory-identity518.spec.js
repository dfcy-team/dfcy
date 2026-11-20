// @vitest-environment jsdom
import {shallowMount,flushPromises} from '@vue/test-utils';
import {reactive} from 'vue';
import {beforeEach,it,expect,vi} from 'vitest';
import Category from '../src/views/inventory/CategoryInventory.vue';
import Warning from '../src/views/inventory/InventoryWarningSnapshot.vue';
const m=vi.hoisted(()=>({auth:null,request:vi.fn(),warnings:vi.fn()}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>m.auth}));
vi.mock('../src/api/request',()=>({requestApi:m.request}));
vi.mock('../src/api/alerts',()=>({fetchInventoryWarnings:m.warnings}));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const mount=C=>shallowMount(C,{global:{stubs:{RouterLink:true,InventoryAbcStatus:true}}});
beforeEach(()=>{m.auth=reactive({currentUser:{id:1,tenant_id:1},authorizationStale:false,hasPermission:()=>true,hasAllDataScopeFor:()=>true});m.request.mockReset();m.warnings.mockReset();});
it('category clears existing evidence and rejects late initial country response on organization change',async()=>{
 const old=deferred();m.request.mockReturnValueOnce(old.promise).mockResolvedValue({success:true,data:{countries:[]}});const w=mount(Category);
 const signal=m.request.mock.calls[0][0].signal;
 w.vm.rows=[{id:10,abc:{sku_grade:'A'}}];
 m.auth.currentUser.tenant_id=2;
 expect(signal.aborted).toBe(true);expect(w.vm.rows).toEqual([]);
 old.resolve({success:true,data:{countries:[{id:7}],results:[{id:10}]}});await flushPromises();
 expect(w.vm.countries).toEqual([]);expect(w.vm.rows).toEqual([]);w.unmount();
});
it('warning aborts old organization reads and clears loaded rows and detail',async()=>{
 const old=deferred();m.warnings.mockReturnValueOnce(old.promise);const w=mount(Warning);
 const signal=m.warnings.mock.calls[0][1];
 w.vm.state={results:[{spu_id:3,abc:{spu_grade:'A'}}]};w.vm.details=[{id:4}];
 m.auth.authorizationStale=true;
 expect(signal.aborted).toBe(true);expect(w.vm.state).toEqual({});expect(w.vm.details).toEqual([]);
 old.resolve({success:true,data:{countries:[{id:7}],results:[{spu_id:3}]}});await flushPromises();
 expect(w.vm.state).toEqual({});expect(w.vm.countries).toEqual([]);w.unmount();
});
