import {describe,it,expect,vi,beforeEach} from 'vitest';
import {shallowMount,flushPromises} from '@vue/test-utils';
const mocks=vi.hoisted(()=>({fetch:vi.fn(),approve:vi.fn(),upload:vi.fn(),confirm:vi.fn()}));
vi.mock('../src/api/workflow',()=>({fetchApproval:mocks.fetch,approveApproval:mocks.approve,rejectApproval:vi.fn(),withdrawApproval:vi.fn()}));
vi.mock('../src/api/feishu',()=>({notifyFeishuApproval:vi.fn()}));
vi.mock('../src/api/paymentRequestsV2',()=>({uploadVoucher:mocks.upload,createIdempotencyKey:()=> 'test-key',downloadVoucher:vi.fn()}));
vi.mock('../src/api/paymentBatchesV2',()=>({upload:mocks.upload,download:vi.fn()}));
vi.mock('vue-router',()=>({useRoute:()=>({params:{id:9}})}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:2},hasPermission:()=>true})}));
vi.mock('element-plus',async(importOriginal)=>({...await importOriginal(),ElMessage:{success:vi.fn(),error:vi.fn()},ElMessageBox:{confirm:mocks.confirm}}));
import View from '../src/views/workflow/ApprovalDetail.vue';
let detail;
beforeEach(()=>{vi.clearAllMocks();detail={id:9,status:'pending',requested_by_id:1,payment_context:{mode:'single',kind:'shipment',source_id:8,request_id:7,version:3,can_post:true,can_upload:true,vouchers:[]}};mocks.fetch.mockImplementation(async()=>({success:true,data:structuredClone(detail)}));mocks.confirm.mockResolvedValue(true);mocks.approve.mockResolvedValue({success:true});});
async function setup(){const w=shallowMount(View);await flushPromises();return w.vm.$.setupState;}
describe('payment approval posting',()=>{
 it('blocks approval without evidence or payment date',async()=>{const s=await setup();s.note='已核实';await s.decide('approve');expect(mocks.approve).not.toHaveBeenCalled();s.detail.payment_context.vouchers=[{id:1}];await s.decide('approve');expect(mocks.approve).not.toHaveBeenCalled();});
 it('submits date and latest version with approval',async()=>{const s=await setup();s.note='已核实转账';s.payment.date='2026-11-01';s.detail.payment_context.vouchers=[{id:1}];await s.decide('approve');expect(mocks.approve).toHaveBeenCalledWith(9,expect.objectContaining({payment:{date:'2026-11-01',reference_number:'',notes:'',expected_version:3}}));});
 it('refreshes version after upload without losing entered date',async()=>{const s=await setup();s.payment.date='2026-11-01';mocks.upload.mockImplementation(async()=>{detail.payment_context.version=4;detail.payment_context.vouchers=[{id:1}];return {success:true};});await s.uploadEvidence({target:{files:[new File(['x'],'proof.png')],value:'x'}});expect(s.detail.payment_context.version).toBe(4);expect(s.payment.date).toBe('2026-11-01');});
 it('blocks financial posting without capability',async()=>{const s=await setup();s.note='核实';s.payment.date='2026-11-01';s.detail.payment_context.vouchers=[{id:1}];s.detail.payment_context.can_post=false;await s.decide('approve');expect(mocks.approve).not.toHaveBeenCalled();});
});
