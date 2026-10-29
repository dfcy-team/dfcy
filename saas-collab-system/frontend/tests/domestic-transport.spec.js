import {beforeEach,describe,expect,it,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
const m=vi.hoisted(()=>({fetch:vi.fn(),save:vi.fn(),key:0}));
vi.mock('../src/api/supplyShipmentsV2',()=>({fetchDomesticCarriers:m.fetch,saveDomesticTransport:m.save,createIdempotencyKey:()=>`transport-${++m.key}`}));
import Panel from '../src/components/supply-chain/DomesticTransportV2.vue';
const panel=(props={})=>mount(Panel,{props:{shipment:{id:1,version:3},editable:true,...props},global:{stubs:{'router-link':true,'el-select':true,'el-input':true,'el-form-item':true,'el-button':true,'el-alert':true}}});
describe('国内承运信息',()=>{
 beforeEach(()=>{m.fetch.mockReset().mockResolvedValue({success:true,data:[{id:8,name:'国内公司'}],count:1});m.save.mockReset().mockResolvedValue({success:true,data:{domestic_carrier_id:8,domestic_carrier_name:'国内公司',domestic_tracking_number:'A01',version:4}});});
 it('loads options only on demand and reuses them',async()=>{const w=panel();await flushPromises();expect(m.fetch).not.toHaveBeenCalled();await w.vm.load();await w.vm.load();expect(m.fetch).toHaveBeenCalledTimes(1);expect(m.fetch).toHaveBeenCalledWith(1,false,{search:'',page:1,page_size:20});w.unmount();});
 it('saves transport separately with optimistic version',async()=>{const w=panel();Object.assign(w.vm.form,{domestic_carrier_id:8,domestic_tracking_number:' A01 '});await w.vm.save();expect(m.save.mock.calls[0].slice(0,3)).toEqual([1,{domestic_carrier_id:8,domestic_tracking_number:'A01',expected_version:3},false]);expect(w.emitted('updated')[0][0].version).toBe(4);w.unmount();});
 it('retains retry key after a failed request',async()=>{m.save.mockRejectedValueOnce(new Error('network'));const w=panel();w.vm.form.domestic_carrier_id=8;await w.vm.save();await w.vm.save();expect(m.save.mock.calls[0][3]).toBe(m.save.mock.calls[1][3]);w.unmount();});
 it('blocks supplier submitted read-only saves',async()=>{const w=panel({supplier:true,editable:false});w.vm.form.domestic_carrier_id=8;await w.vm.save();expect(m.save).not.toHaveBeenCalled();w.unmount();});
 it('discards option responses from another shipment',async()=>{let resolve;m.fetch.mockReturnValueOnce(new Promise(r=>resolve=r));const w=panel();const pending=w.vm.load();await w.setProps({shipment:{id:2,version:1}});resolve({success:true,data:[{id:99,name:'旧数据'}]});await pending;expect(w.vm.rows).toEqual([]);w.unmount();});
});
