import {beforeEach,describe,expect,it,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
const m=vi.hoisted(()=>({get:vi.fn(),save:vi.fn(),issue:vi.fn(),download:vi.fn(),history:vi.fn(),reissue:vi.fn(),key:0,manage:true}));
vi.mock('../src/api/purchaseContractsV2',()=>({fetchContract:m.get,fetchContractHistory:m.history,reissueContract:m.reissue,saveContract:m.save,issueContract:m.issue,downloadContract:m.download,createIdempotencyKey:()=>`contract-${++m.key}`}));
vi.mock('../src/stores/auth',()=>({useAuthStore:()=>({currentUser:{id:1},authorizationStale:false,hasPermission:()=>m.manage})}));
import Contract from '../src/components/supply-chain/PurchaseContractV2.vue';
const global={stubs:{'el-drawer':true,'el-button':true},directives:{loading:{}}};
const payload=()=>({buyer:{name:''},seller:{name:'供应商'},contract_date:null,include_order_number:true,pricing_basis:'net_plus_tax',lines:[],terms:[]});
const result=(contract=null)=>({success:true,data:{contract,defaults:payload(),source_version:4,shipment_number:'PHSH001'}});
describe('采购合同编辑和正式生成',()=>{
 beforeEach(()=>{m.manage=true;m.key=0;m.get.mockReset().mockResolvedValue(result());m.save.mockReset().mockResolvedValue(result({version:1,status:'draft',nature:'corporate',payload:payload()}));m.issue.mockReset().mockResolvedValue(result({version:2,status:'issued',number:'HT001',nature:'corporate',payload:payload()}));});
 it('lazy loads and preserves edits and idempotency key after a failed save',async()=>{const w=mount(Contract,{props:{shipmentId:3},global});await flushPromises();expect(m.get).not.toHaveBeenCalled();await w.vm.open();w.vm.payload.buyer.name='买方';w.vm.reason='首次确认';m.save.mockRejectedValueOnce(new Error('网络中断'));await w.vm.save();expect(w.vm.payload.buyer.name).toBe('买方');await w.vm.save();expect(m.save.mock.calls[0][2]).toBe(m.save.mock.calls[1][2]);expect(m.save.mock.calls[0][1]).toMatchObject({expected_version:0,expected_source_version:4,reason:'首次确认'});w.unmount();});
 it('requires saved content and explicit confirmation before issue',async()=>{const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();await w.vm.issue();expect(m.issue).not.toHaveBeenCalled();w.vm.reason='保存';await w.vm.save();await flushPromises();w.vm.confirmed=true;w.vm.payload.buyer.name='未保存修改';await w.vm.issue();expect(m.issue).not.toHaveBeenCalled();w.vm.reason='更正';await w.vm.save();await flushPromises();w.vm.confirmed=true;await w.vm.issue();expect(m.issue.mock.calls[0][1]).toEqual({expected_version:1,expected_source_version:4,confirmed:true});await w.vm.issue();expect(m.issue).toHaveBeenCalledTimes(1);w.unmount();});
 it('does not write without reason or write permission',async()=>{const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();await w.vm.save();expect(m.save).not.toHaveBeenCalled();m.manage=false;w.vm.reason='填写';await w.vm.save();expect(m.save).not.toHaveBeenCalled();w.unmount();});
 it('shows field validation details without clearing user input',async()=>{const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();w.vm.reason='核对';m.save.mockResolvedValueOnce({success:false,message:'校验失败',data:{payload:{lines:[{tax_rate:['请输入税率']}]}}});await w.vm.save();expect(w.vm.error).toContain('税率');expect(w.vm.error).toContain('第1行');expect(w.vm.reason).toBe('核对');w.unmount();});
 it('sends the chosen cost treatment and manually overridden tax rate',async()=>{const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();w.vm.payload.tax_treatment='exempt';w.vm.payload.lines=[{tax_rate:'13',unit_price:'100',quantity:'1'}];w.vm.reason='确认免税';await w.vm.save();expect(m.save.mock.calls[0][1].payload).toMatchObject({pricing_basis:'net_plus_tax',tax_treatment:'exempt',lines:[{tax_rate:'13'}]});w.unmount();});
 it('prevents issuing a legacy draft until its pricing basis is saved',async()=>{const old=payload();delete old.pricing_basis;m.get.mockResolvedValueOnce(result({version:1,status:'draft',nature:'corporate',payload:old}));const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();w.vm.confirmed=true;await w.vm.issue();expect(m.issue).not.toHaveBeenCalled();w.unmount();});
 it('discards responses for a previous shipment',async()=>{let resolve;m.get.mockReturnValueOnce(new Promise(r=>resolve=r));const w=mount(Contract,{props:{shipmentId:3},global});const pending=w.vm.open();await w.setProps({shipmentId:4});resolve(result());await pending;expect(w.vm.payload).toBeNull();w.unmount();});
});

it('keeps edits across sections and distinguishes missing tax from missing price',async()=>{m.get.mockResolvedValue(result());const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();w.vm.payload.buyer.name='保留草稿';w.vm.section='goods';w.vm.expanded=true;expect(w.vm.payload.buyer.name).toBe('保留草稿');expect(w.vm.taxPreview({quantity:2,unit_price:'100',tax_rate:''})).toBe('待填写税点');w.unmount();});

it('requires a reissue draft before a voided contract can be edited or issued',async()=>{
 m.manage=true;m.save.mockClear();m.issue.mockClear();m.get.mockResolvedValue(result({version:4,status:'voided',number:'OLD',nature:'corporate',payload:payload()}));
 m.history.mockResolvedValue({success:true,data:{history:[{id:1,number:'OLD'}],count:1}});
 m.reissue.mockResolvedValue(result({version:5,status:'draft',nature:'corporate',payload:payload()}));
 const w=mount(Contract,{props:{shipmentId:3},global});await w.vm.open();w.vm.reason='edit';w.vm.confirmed=true;
 await w.vm.save();await w.vm.issue();expect(m.save).not.toHaveBeenCalled();expect(m.issue).not.toHaveBeenCalled();
 await w.vm.loadHistory();expect(w.vm.historyRows[0].number).toBe('OLD');
 await w.vm.reissue();expect(m.reissue.mock.calls.at(-1)[1]).toEqual({expected_version:4});expect(w.vm.contract.status).toBe('draft');w.unmount();
});


describe('采购合同分区导航',()=>{
 it('scrolls only the nearest drawer and keeps draft input when switching sections',async()=>{
  const outer=document.createElement('div');outer.className='el-drawer__body';const inner=document.createElement('div');inner.className='el-drawer__body';outer.append(inner);document.body.append(outer);
  const scroll=vi.fn();inner.scrollTo=scroll;outer.scrollTo=vi.fn();
  const w=mount(Contract,{props:{shipmentId:3},global:{...global,stubs:{...global.stubs,'el-drawer':{template:`<div class=\"el-drawer__body\"><slot /></div>`}}},attachTo:inner});await w.vm.open();w.vm.payload.buyer.name='保留草稿';const closest=vi.fn(()=>inner);w.vm.panelRoot.closest=closest;w.vm.changeSection('goods');expect(closest).toHaveBeenCalledWith('.el-drawer__body');
  expect(scroll).toHaveBeenCalledWith({top:0,behavior:'smooth'});expect(outer.scrollTo).not.toHaveBeenCalled();expect(w.vm.payload.buyer.name).toBe('保留草稿');
  w.unmount();outer.remove();
 });
});
