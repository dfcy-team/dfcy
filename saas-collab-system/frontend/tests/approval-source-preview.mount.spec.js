import { mount, flushPromises } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchApproval, fetchCostContext, previewVoucher, approveApproval, rejectApproval, routeParams, routeProxy } = vi.hoisted(() => ({ fetchApproval: vi.fn(), fetchCostContext: vi.fn(), previewVoucher: vi.fn(), approveApproval: vi.fn(), rejectApproval: vi.fn(), routeParams: { id: '8' }, routeProxy: { current: null } }));
vi.mock('../src/api/workflow', () => ({ fetchApproval, approveApproval, rejectApproval, withdrawApproval: vi.fn() }));
vi.mock('../src/api/feishu', () => ({ notifyFeishuApproval: vi.fn() }));
vi.mock('../src/api/supplyCostsV2', () => ({ fetchCostContext }));
vi.mock('../src/api/paymentRequestsV2', () => ({ createIdempotencyKey: vi.fn(), uploadVoucher: vi.fn(), downloadVoucher: vi.fn(), previewVoucher }));
vi.mock('../src/api/paymentBatchesV2', () => ({ upload: vi.fn(), download: vi.fn() }));
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ currentUser: { id: 2 }, hasPermission: () => true }) }));
vi.mock('vue-router', async () => { const { reactive } = await import('vue'); routeProxy.current = reactive(routeParams); return { useRoute: () => ({ params: routeProxy.current }) }; });
vi.mock('element-plus', async (importOriginal) => ({ ...(await importOriginal()), ElMessage: { error: vi.fn(), success: vi.fn() }, ElMessageBox: { confirm: vi.fn() } }));

import ApprovalDetail from '../src/views/workflow/ApprovalDetail.vue';

const stub = (tag, props = []) => defineComponent({ name: tag, props, emits: ['update:modelValue'], setup(p, { slots, emit, attrs }) {
  return () => tag === 'el-dialog'
    ? (p.modelValue ? h('div', { class: 'dialog' }, [slots.default?.(), slots.footer?.({ close: () => emit('update:modelValue', false) })]) : null)
    : tag === 'el-button'
      ? h('button', { ...attrs, onClick: (event) => { attrs.onClick?.(event); } }, slots.default?.())
      : tag === 'el-input'
        ? h('textarea', { value: p.modelValue, onInput: (event) => emit('update:modelValue', event.target.value), placeholder: attrs.placeholder })
        : h('div', { ...attrs, class: attrs.class }, slots.default?.());
} });

const stubs = Object.fromEntries(['el-alert','el-card','el-descriptions','el-descriptions-item','el-tag','el-form','el-form-item','el-date-picker','el-input','el-button','el-dialog','el-table','el-table-column','el-timeline','el-timeline-item','el-empty','router-link'].map(name => [name, stub(name, ['modelValue','title','type','label','span','data','prop','width','minWidth','rows','maxlength','placeholder'])]));
stubs['el-table'] = defineComponent({ name: 'el-table', props: ['data'], setup: (props) => () => h('div', { class: 'source-rows' }, (props.data || []).map(row => h('div', { key: row.shipment_line_id }, `${row.product_name} ${row.sku} ${row.quantity}`))) });

describe('approval source preview interaction', () => {
  beforeEach(() => {
    routeParams.id = '8';
    approveApproval.mockReset();rejectApproval.mockReset();
    fetchApproval.mockReset().mockResolvedValue({ success: true, data: {
      id: 8, status: 'pending', requested_by_id: 3, business_link: '/supply-chain/costs?tab=reconciliation', business_reference: 'SHIP-42',
      payment_context: { kind: 'shipment', source_id: 42 },
      payment_display: { amount: '125.00', payment_object: '供应商甲', payment_type: '供应商货款', reason: '货款申请' }
    } });
    fetchCostContext.mockReset().mockResolvedValue({ success: true, data: {
      target: { number: 'SHIP-42', stage: 'submitted' },
      measurements: [{ shipment_line_id: 9, product_name: '产品A', sku: 'SKU-A', quantity: 4 }]
    } });
  });

  it('loads on click, shows read-only source and payment details, and preserves approval note when closed', async () => {
    const wrapper = mount(ApprovalDetail, { global: { stubs } });
    await flushPromises();
    expect(fetchCostContext).not.toHaveBeenCalled();
    const note = wrapper.find('textarea');
    await note.setValue('请核对付款凭证');
    const open = wrapper.findAll('button').find(button => button.text().includes('预览来源单据'));
    await open.trigger('click');
    await flushPromises();
    expect(fetchCostContext).toHaveBeenCalledWith('shipment', 42);
    expect(wrapper.text()).toContain('SHIP-42');
    expect(wrapper.text()).toContain('产品A');
    expect(wrapper.text()).toContain('125.00');
    expect(wrapper.text()).toContain('供应商甲');
    const close = wrapper.findAll('button').find(button => button.text() === '关闭');
    await close.trigger('click');
    await flushPromises();
    expect(wrapper.find('.dialog').exists()).toBe(false);
    expect(wrapper.find('textarea').element.value).toBe('请核对付款凭证');
  });
});

it('clears approval-local fields and aborts a confirmed decision after route change',async()=>{
 let finishConfirm;const {ElMessageBox}=await import('element-plus');ElMessageBox.confirm.mockReturnValueOnce(new Promise(resolve=>finishConfirm=resolve));
 fetchApproval.mockReset().mockImplementation(id=>Promise.resolve({success:true,data:{id:Number(id),status:'pending',requested_by_id:3,title:`approval-${id}`,payment_context:{mode:'batch',batch_id:Number(id),version:Number(id)}}}));
 const wrapper=mount(ApprovalDetail,{global:{stubs}});await flushPromises();await wrapper.find('textarea').setValue('A only note');
 await wrapper.findAll('button').find(button=>button.text()==='驳回').trigger('click');
 routeProxy.current.id='9';await wrapper.vm.$nextTick();await flushPromises();expect(wrapper.text()).toContain('approval-9');expect(wrapper.find('textarea').element.value).toBe('');
 finishConfirm();await flushPromises();expect(rejectApproval).not.toHaveBeenCalled();wrapper.unmount();routeParams.id='8';
});

it('discards a source preview response after switching approval routes',async()=>{
 routeParams.id='8';fetchApproval.mockReset().mockResolvedValue({success:true,data:{id:8,status:'pending',business_link:'/costs',business_reference:'A',payment_context:{kind:'shipment',source_id:42}}});
 let finishSource;fetchCostContext.mockReturnValueOnce(new Promise(resolve=>finishSource=resolve));
 const wrapper=mount(ApprovalDetail,{global:{stubs}});await flushPromises();
 await wrapper.findAll('button').find(button=>button.text().includes('预览来源单据')).trigger('click');
 routeProxy.current.id='9';await wrapper.vm.$nextTick();await flushPromises();
 finishSource({success:true,data:{target:{number:'STALE-SOURCE'},measurements:[]}});await flushPromises();expect(wrapper.text()).not.toContain('STALE-SOURCE');expect(wrapper.find('.dialog').exists()).toBe(false);
 wrapper.unmount();routeParams.id='8';
});

it('invalidates pending voucher preview on unmount and route changes discard stale approval responses',async()=>{
 const create=vi.fn(()=> 'blob:approval'),revoke=vi.fn();vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:revoke});
 fetchApproval.mockReset().mockResolvedValue({success:true,data:{id:8,status:'pending',payment_context:{mode:'single',kind:'shipment',source_id:4,request_id:8,vouchers:[{id:2,file_name:'x.png',media_type:'image/png'}]}}});
 let finishPreview;previewVoucher.mockReturnValueOnce(new Promise(r=>finishPreview=r));const wrapper=mount(ApprovalDetail,{global:{stubs}});await flushPromises();const btn=wrapper.findAll('button').find(b=>b.text().includes('x.png'));expect(btn).toBeTruthy();await btn.trigger('click');wrapper.unmount();finishPreview({success:true,blob:new Blob(['late'],{type:'image/png'})});await flushPromises();expect(create).not.toHaveBeenCalled();
 routeParams.id='8';let resolveOld;fetchApproval.mockReset().mockImplementation(id=>id==='8'?new Promise(r=>resolveOld=r):Promise.resolve({success:true,data:{id:9,title:'new route'}}));
 const routed=mount(ApprovalDetail,{global:{stubs}});await flushPromises();routeProxy.current.id='9';await routed.vm.$nextTick();await flushPromises();expect(routed.text()).toContain('new route');resolveOld({success:true,data:{id:8,title:'old route'}});await flushPromises();expect(routed.text()).toContain('new route');expect(routed.text()).not.toContain('old route');routed.unmount();routeParams.id='8';vi.unstubAllGlobals();
});
