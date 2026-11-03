import { shallowMount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ createPaymentFlow:vi.fn(), fetchPaymentFlowDepartments:vi.fn(), fetchPaymentFlowReviewers:vi.fn(), fetchPaymentFlows:vi.fn(), updatePaymentFlowStatus:vi.fn() }));
vi.mock('../src/api/workflow', () => api);
import PaymentFlowManagement from '../src/views/workflow/PaymentFlowManagement.vue';
beforeEach(()=>{vi.resetAllMocks(); for(const key of ['fetchPaymentFlows','fetchPaymentFlowDepartments','fetchPaymentFlowReviewers'])api[key].mockResolvedValue({success:true,data:[]});});
const mountPage=()=>shallowMount(PaymentFlowManagement,{global:{directives:{loading:()=>{}}}});
describe('payment flow API failures',()=>{
 it('preserves draft and displays server error when save resolves unsuccessful',async()=>{
 const w=mountPage();await flushPromises();Object.assign(w.vm.form,{flow_key:'keep-draft',reviewer_id:'3',minimum_amount:'25',payment_kinds:['purchase'],natures:['corporate']});
 api.createPaymentFlow.mockResolvedValue({success:false,message:'保存校验失败'});await w.vm.save(false);
 expect(w.vm.form.flow_key).toBe('keep-draft');expect(w.vm.form.minimum_amount).toBe('25');expect(w.vm.error).toBe('保存校验失败');expect(api.fetchPaymentFlows).toHaveBeenCalledTimes(1);w.unmount();
 });
 it.each(['publish','disable'])('keeps state and shows failure for %s',async(action)=>{
 const w=mountPage();await flushPromises();api.updatePaymentFlowStatus.mockResolvedValue({success:false,message:'状态修改失败'});await w.vm.act({id:4},action);
 expect(w.vm.error).toBe('状态修改失败');expect(api.fetchPaymentFlows).toHaveBeenCalledTimes(1);expect(w.vm.saving).toBe(false);w.unmount();
 });
 it('shows a failed load rather than treating it as an empty configuration',async()=>{
 api.fetchPaymentFlows.mockResolvedValue({success:false,message:'流程读取失败'});const w=mountPage();await flushPromises();expect(w.vm.error).toBe('流程读取失败');w.unmount();
 });
});
