import {beforeEach,describe,expect,it,vi} from 'vitest';
import {mount} from '@vue/test-utils';
const m=vi.hoisted(()=>({get:vi.fn(),save:vi.fn(),key:0,manage:true}));
vi.mock('../src/api/payableClassificationV2',()=>({fetchPayableClassification:m.get,savePayableClassification:m.save,createIdempotencyKey:()=>`split-${++m.key}`}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:1},authorizationStale:false,hasPermission:()=>m.manage})}));
import Panel from '../src/components/supply-chain/PayableClassificationPanelV2.vue';
const global={stubs:{'el-button':true,'el-form':true,'el-form-item':true,'el-input':true,'el-alert':true},directives:{loading:{}}};
const result=()=>({success:true,data:{version:0,source_version:2,payable_amount:'100.0000',currency:'CNY',party_name:'供应商',can_manage:true,corporate_amount:'0',personal_amount:'0'}});
async function draft(){const w=mount(Panel,{props:{kind:'shipment',id:2},global});await w.vm.toggle();w.vm.corporate='60';w.vm.personal='30';w.vm.reason='双方确认';return w;}
describe('应付性质独立维护',()=>{
 beforeEach(()=>{m.manage=true;m.get.mockReset().mockResolvedValue(result());m.save.mockReset().mockResolvedValue(result());});
 it('saves full obligation split with unclassified remainder and no account',async()=>{const w=await draft();expect(w.vm.unclassified).toBe('10.0000');await w.vm.save();expect(m.save.mock.calls[0][2]).toEqual({expected_version:0,expected_source_version:2,expected_payable_amount:'100.0000',currency:'CNY',corporate_amount:'60',personal_amount:'30',reason:'双方确认'});expect(w.emitted('updated')).toHaveLength(1);w.unmount();});
 it('rejects over-allocation and negative amounts precisely',async()=>{const w=await draft();w.vm.personal='40.0001';await w.vm.save();expect(m.save).not.toHaveBeenCalled();expect(w.vm.error).toContain('超过');w.vm.personal='-1';await w.vm.save();expect(m.save).not.toHaveBeenCalled();w.unmount();});
 it('retains the idempotency key for a failed retry',async()=>{const w=await draft();m.save.mockRejectedValueOnce(new Error('网络中断'));await w.vm.save();await w.vm.save();expect(m.save.mock.calls[0][3]).toBe(m.save.mock.calls[1][3]);w.unmount();});
 it('blocks read only and unknown payable',async()=>{const w=await draft();w.vm.data.payable_amount=null;await w.vm.save();expect(m.save).not.toHaveBeenCalled();w.vm.data.payable_amount='100';w.vm.data.can_manage=false;await w.vm.save();expect(m.save).not.toHaveBeenCalled();w.unmount();});
 it('discards stale load after changing document',async()=>{let resolve;m.get.mockReturnValueOnce(new Promise(r=>resolve=r));const w=mount(Panel,{props:{kind:'shipment',id:2},global});const pending=w.vm.toggle();await w.setProps({id:3});resolve(result());await pending;expect(w.vm.data).toBeNull();w.unmount();});
});
