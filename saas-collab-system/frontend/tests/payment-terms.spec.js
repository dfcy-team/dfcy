import {beforeEach,describe,expect,it,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
const m=vi.hoisted(()=>({get:vi.fn(),save:vi.fn(),reminders:vi.fn(),key:0,manage:true}));
vi.mock('../src/api/paymentTermsV2',()=>({fetchPaymentTerms:m.get,savePaymentTerms:m.save,fetchPaymentReminders:m.reminders,createIdempotencyKey:()=>`term-${++m.key}`}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:1},authorizationStale:false,hasPermission:()=>m.manage})}));
import Terms from '../src/components/supply-chain/PaymentTermsPanelV2.vue';
import Reminders from '../src/components/supply-chain/PaymentRemindersV2.vue';
const global={stubs:{'el-button':true,'el-form':true,'el-select':true,'el-input-number':true,'el-input':true,'el-date-picker':true,'el-table':true,'el-pagination':true},directives:{loading:{}}};
const result=()=>({success:true,data:{version:2,days:30,start:'reconciliation_date',reminder_days:7,due_date:null,status:'unknown',history:[]}});
describe('付款账期与提醒',()=>{
 beforeEach(()=>{m.manage=true;m.get.mockReset().mockResolvedValue(result());m.save.mockReset().mockResolvedValue(result());m.reminders.mockReset().mockResolvedValue({success:true,data:[{id:8,kind:'batch'}],count:1});});
 it('loads terms only when expanded and preserves idempotency on retry',async()=>{const w=mount(Terms,{props:{kind:'batch',id:3},global});await flushPromises();expect(m.get).not.toHaveBeenCalled();await w.vm.toggle();w.vm.form.reason='双方确认';w.vm.form.due_date_override='2026-11-15';m.save.mockRejectedValueOnce(new Error('网络中断'));await w.vm.save();expect(w.vm.form.reason).toBe('双方确认');await w.vm.save();expect(m.save.mock.calls[0][3]).toBe(m.save.mock.calls[1][3]);expect(m.save.mock.calls[1][2]).toMatchObject({reason:'双方确认',expected_version:2,due_date_override:'2026-11-15'});w.unmount();});
 it('requires a reason and blocks read-only writes',async()=>{const w=mount(Terms,{props:{kind:'shipment',id:2},global});await w.vm.toggle();await w.vm.save();expect(m.save).not.toHaveBeenCalled();w.unmount();m.manage=false;const readonly=mount(Terms,{props:{kind:'shipment',id:2},global});await readonly.vm.toggle();readonly.vm.form.reason='测试';await readonly.vm.save();expect(m.save).not.toHaveBeenCalled();readonly.unmount();});
 it('discards terms from an old document',async()=>{let resolve;m.get.mockReturnValueOnce(new Promise(r=>resolve=r));const w=mount(Terms,{props:{kind:'shipment',id:2},global});const pending=w.vm.toggle();await w.setProps({id:3});resolve(result());await pending;expect(w.vm.data).toBeNull();w.unmount();});
 it('requests bounded reminder pages with the country and selected type',async()=>{const w=mount(Reminders,{props:{countryId:7},global});expect(m.reminders).not.toHaveBeenCalled();w.vm.kind='inbound';w.vm.status='unknown';await w.vm.toggle();expect(m.reminders).toHaveBeenCalledWith({kind:'inbound',status:'unknown',country_id:7,limit:20,offset:0});expect(w.vm.total).toBe(1);w.unmount();});
 it('discards stale country reminders',async()=>{let resolve;m.reminders.mockReturnValueOnce(new Promise(r=>resolve=r));const w=mount(Reminders,{props:{countryId:7},global});const pending=w.vm.toggle();await w.setProps({countryId:8});await flushPromises();resolve({success:true,data:[{id:99}],count:1});await pending;expect(w.vm.rows[0].id).toBe(8);w.unmount();});
});
