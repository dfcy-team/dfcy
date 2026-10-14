import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
const api = vi.hoisted(() => ({ fetchReconciliationMatchDetail: vi.fn(), confirmReconciliationMatch: vi.fn(), rejectReconciliationMatch: vi.fn(), fetchReconciliationMatches: vi.fn(), fetchPlatformStatements: vi.fn(), fetchWithdrawalRecords: vi.fn(), fetchBankReceipts: vi.fn(), createReconciliationMatch: vi.fn() }));
const imports = vi.hoisted(() => ({ fetchFinanceImports: vi.fn(), submitFinanceImport: vi.fn() }));
const nav = vi.hoisted(() => ({ route: { params: { id: '7' } }, push: vi.fn() }));
const dialogs = vi.hoisted(() => ({ confirm: vi.fn(), prompt: vi.fn() }));
const financeAccess = vi.hoisted(() => ({ reconcile: true }));
vi.mock('../src/api/financeReconciliation', () => api);
vi.mock('../src/api/financeImports', () => imports);
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: code => code === 'finance.reconcile' ? financeAccess.reconcile : true }) }));
vi.mock('vue-router', () => ({ useRoute: () => nav.route, useRouter: () => ({ push: nav.push }) }));
vi.mock('element-plus', async importOriginal => ({ ...await importOriginal(), ElMessageBox: dialogs, ElMessage: { success: vi.fn() } }));
import MatchDetail from '../src/views/finance/ReconciliationMatchDetail.vue';
import ImportPage from '../src/views/finance/FinanceImportList.vue';
import MatchList from '../src/views/finance/ReconciliationMatchList.vue';
import { financeError, recentFinancePeriod } from '../src/views/finance/financePresentation';
const stubs = {
  'el-button': { props:['disabled'], template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-alert': { props:['title'], template:'<div>{{title}}</div>' },
  'el-descriptions': { template:'<div><slot /></div>' }, 'el-descriptions-item': { template:'<div><slot /></div>' },
  'el-skeleton':true, 'el-empty':true, 'el-form':{ template:'<form @submit.prevent="$emit(\'submit\',$event)"><slot /></form>' }, 'el-form-item':{template:'<label><slot /></label>'},
  'el-select':{ template:'<select><slot /></select>' }, 'el-option':true,
  'el-table': { props:['data'], template:'<div><slot /></div>' }, 'el-table-column':true,
  'el-dialog':{props:['modelValue'],template:'<div v-if="modelValue"><slot /></div>'}
};
const render = component => mount(component,{global:{stubs}});
beforeEach(() => { vi.clearAllMocks(); financeAccess.reconcile=true; nav.route.params.id='7'; dialogs.confirm.mockResolvedValue('confirm'); dialogs.prompt.mockResolvedValue({value:'wrong reference'}); api.fetchReconciliationMatchDetail.mockResolvedValue({success:true,data:{id:7,status:'suggested',difference_amount:'0.00',statement_no:'ST-7',withdrawal_no:'W-7',receipt_reference:'R-7'}}); api.rejectReconciliationMatch.mockResolvedValue({success:true}); api.confirmReconciliationMatch.mockResolvedValue({success:true}); });
describe('财务复核必须展示正确记录', () => {
  it.each([{id:8,status:'suggested'},[{id:7,status:'suggested'}]])('错误对象或数组禁止复核 %j', async data => { api.fetchReconciliationMatchDetail.mockResolvedValue({success:true,data}); const w=render(MatchDetail); await flushPromises(); expect(w.text()).toContain('已禁止复核'); expect(w.findAll('button').some(b => b.text()==='确认匹配')).toBe(false); expect(api.confirmReconciliationMatch).not.toHaveBeenCalled(); w.unmount(); });
  it('显示凭据并要求拒绝原因，使用当前记录ID', async () => { const w=render(MatchDetail); await flushPromises(); expect(w.text()).toContain('ST-7'); await w.findAll('button').find(b=>b.text()==='拒绝匹配').trigger('click'); await flushPromises(); expect(api.rejectReconciliationMatch).toHaveBeenCalledWith(7,'wrong reference'); w.unmount(); });
  it('非零差额无法直接确认',async()=>{ api.fetchReconciliationMatchDetail.mockResolvedValue({success:true,data:{id:7,status:'suggested',difference_amount:'-5.00'}}); const w=render(MatchDetail); await flushPromises(); expect(w.findAll('button').find(b=>b.text()==='确认匹配').attributes('disabled')).toBeDefined(); w.unmount(); });
  it('已处理记录没有复核按钮',async()=>{ api.fetchReconciliationMatchDetail.mockResolvedValue({success:true,data:{id:7,status:'confirmed',difference_amount:'0'}}); const w=render(MatchDetail); await flushPromises(); expect(w.findAll('button').some(b=>b.text()==='确认匹配')).toBe(false); w.unmount(); });
  it('只读财务用户没有创建或复核操作且不发写请求',async()=>{ financeAccess.reconcile=false; api.fetchReconciliationMatches.mockResolvedValue({success:true,data:[]}); const list=render(MatchList); const detail=render(MatchDetail); await flushPromises(); expect(list.findAll('button').some(b=>b.text()==='新建人工匹配')).toBe(false); expect(detail.findAll('button').some(b=>['确认匹配','拒绝匹配'].includes(b.text()))).toBe(false); expect(api.createReconciliationMatch).not.toHaveBeenCalled(); expect(api.confirmReconciliationMatch).not.toHaveBeenCalled(); expect(api.rejectReconciliationMatch).not.toHaveBeenCalled(); list.unmount(); detail.unmount(); });
});
describe('财务导入和人工匹配错误处理',()=>{
  it('预检失败不能提交，并展示行号错误',async()=>{ imports.fetchFinanceImports.mockResolvedValue({success:true,data:{templates:{statements:['statement_no']},history:[]}}); imports.submitFinanceImport.mockResolvedValue({success:false,message:'invalid',data:{rows:[{row:3,fields:{net_amount:['净额不一致']}}]}}); const w=render(ImportPage); await flushPromises(); const input=w.find('input[type=file]'); Object.defineProperty(input.element,'files',{value:[new File(['a'],'facts.csv')],configurable:true}); await input.trigger('change'); await w.find('form').trigger('submit'); await flushPromises(); expect(w.text()).toContain('第 3 行'); const commit=w.findAll('button').find(b=>b.text().startsWith('确认导入')); expect(commit.attributes('disabled')).toBeDefined(); w.unmount(); });
  it('人工匹配只加载已完成提现和待匹配到账',async()=>{ api.fetchReconciliationMatches.mockResolvedValue({success:true,data:[]}); [api.fetchPlatformStatements,api.fetchWithdrawalRecords,api.fetchBankReceipts].forEach(fn=>fn.mockResolvedValue({success:true,data:[]})); const w=render(MatchList); await flushPromises(); await w.findAll('button').find(b=>b.text()==='新建人工匹配').trigger('click'); await flushPromises(); expect(api.fetchWithdrawalRecords).toHaveBeenCalledWith({status:'completed'}); expect(api.fetchBankReceipts).toHaveBeenCalledWith({status:'imported'}); expect(w.text()).toContain('缺少可用'); expect(api.createReconciliationMatch).not.toHaveBeenCalled(); w.unmount(); });
  it('近期日期跨月跨年准确，行错误保留编号',()=>{ expect(recentFinancePeriod(new Date('2026-01-10T00:00:00Z'))).toEqual(['2025-12-12','2026-01-10']); expect(financeError({data:{rows:[{row:8,fields:{currency:['错误']}}]}})).toContain('第 8 行'); });
});
