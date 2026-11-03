import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { ledgerMoney, ledgerCsv } from '../src/views/finance/ledgerPresentation';

const api = vi.hoisted(() => ({ fetchFinanceLedger:vi.fn() }));
const nav = vi.hoisted(() => ({ query:{}, push:vi.fn() }));
vi.mock('../src/api/financeReconciliation', () => api);
vi.mock('vue-router', () => ({ useRoute:() => ({ query:nav.query }), useRouter:() => ({ push:nav.push }) }));
import Ledger from '../src/views/finance/FinanceLedger.vue';
const pass = { template:'<div><slot /></div>' };
const stubs = Object.fromEntries(['el-form','el-form-item','el-table','el-radio-group','el-radio-button'].map(name => [name,pass]));
Object.assign(stubs, {
  'el-button':{ props:['disabled'], emits:['click'], template:'<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-alert':{ props:['title'], template:'<p>{{title}}</p>' }, 'el-table-column':true,
  'el-date-picker':true, 'el-select':true, 'el-input':true, 'el-option':true,
  'el-pagination':true, 'el-drawer':{ props:['modelValue'], template:'<aside v-if="modelValue"><slot /></aside>' }
});
const response = (currency='CNY') => ({ success:true, data:{ items:[], pagination:{page:1,page_size:20,total:0},
  totals:[{currency,income:'0',expense:'-2.900000',balance:'-2.900000',pending_count:0}],
  notices:['实际成本快照缺失，不代表成本为零'], stores:[], source_count:1, coverage:{warehouse_order:1} } });
const render = () => mount(Ledger,{global:{stubs,directives:{loading:() => {}}}});
beforeEach(() => { vi.clearAllMocks(); nav.query={}; api.fetchFinanceLedger.mockResolvedValue(response()); });

describe('真实财务流水', () => {
  it('提示参考退款已隐藏，分页使用后端的可见记录总数',async () => {
    const result=response(); result.data.hidden_reference_refund_count=1; result.data.pagination.total=1;
    api.fetchFinanceLedger.mockResolvedValue(result);
    const wrapper=render(); await flushPromises();
    expect(wrapper.text()).toContain('已隐藏 1 笔参考退款');
    expect(wrapper.text()).toContain('不影响金额合计');
    expect(wrapper.text()).toContain('1 笔 · 1 个来源');
    expect(wrapper.text()).toContain('-2.90'); wrapper.unmount();
  });
  it('按原币展示、显示缺口，默认最近30天且无写请求',async () => {
    const wrapper=render(); await flushPromises();
    expect(api.fetchFinanceLedger).toHaveBeenCalledWith(expect.objectContaining({view:'detail',all_history:false,page:1}));
    expect(wrapper.text()).toContain('CNY'); expect(wrapper.text()).toContain('-2.90');
    expect(wrapper.text()).toContain('实际成本快照缺失'); wrapper.unmount();
  });
  it('全部历史保留无日期查询，失败时清空旧金额',async () => {
    const wrapper=render(); await flushPromises(); api.fetchFinanceLedger.mockRejectedValueOnce(new Error('后端不可用'));
    await wrapper.findAll('button').find(b => b.text()==='全部历史').trigger('click'); await flushPromises();
    expect(api.fetchFinanceLedger).toHaveBeenLastCalledWith(expect.objectContaining({all_history:true,period_start:undefined}));
    expect(wrapper.text()).toContain('后端不可用'); expect(wrapper.text()).not.toContain('-2.90'); wrapper.unmount();
  });
  it('较早返回的请求不能覆盖新筛选',async () => {
    let first; api.fetchFinanceLedger.mockImplementationOnce(() => new Promise(resolve => { first=resolve; }));
    const wrapper=render(); await wrapper.findAll('button').find(b=>b.text()==='全部历史').trigger('click'); await flushPromises();
    first(response('USD')); await flushPromises(); expect(wrapper.text()).toContain('CNY'); expect(wrapper.text()).not.toContain('USD'); wrapper.unmount();
  });
  it('继承页面日期与店铺条件',async () => {
    nav.query={store_id:'30',period_start:'2026-06-01',period_end:'2026-06-30'};
    const wrapper=render(); await flushPromises();
    expect(api.fetchFinanceLedger).toHaveBeenCalledWith(expect.objectContaining({store_id:30,period_start:'2026-06-01',period_end:'2026-06-30'})); wrapper.unmount();
  });
  it('金额构成下钻保留原分摊维度，不改为重新分摊的明细查询',async () => {
    const wrapper=render(); await flushPromises(); wrapper.vm.view='order'; await wrapper.vm.search(); await flushPromises();
    wrapper.vm.openComposition({country:'PH',currency:'CNY',store_id:30,external_order_id:'ORDER-1'},'warehouse_other'); await flushPromises();
    expect(api.fetchFinanceLedger).toHaveBeenLastCalledWith(expect.objectContaining({view:'order',breakdown:true,store_id:30,kind:'warehouse_other',external_order_id:'ORDER-1'})); wrapper.unmount();
  });
});

describe('精确金额与导出', () => {
  it('不使用浮点数舍入大额或六位小数',() => {
    expect(ledgerMoney('123456789012345.123456')).toBe('123,456,789,012,345.123456');
    expect(ledgerMoney('-2.900000')).toBe('-2.90'); expect(ledgerMoney(null)).toBe('—');
    expect(ledgerMoney('0.000001')).toBe('0.000001');
  });
  it('缺失不导出为0，参考项不冒充已确认金额；防CSV公式注入',() => {
    const csv=ledgerCsv([{country:'PH',store_code:'=HYPERLINK("x")',external_order_id:'01',currency:'PHP',cells:{refund:{reference_amount:'-20'}},balance:'80',pending_count:0}],'order',{receipt:'订单回款',refund:'订单退款'});
    expect(csv).toContain("'=HYPERLINK"); expect(csv).toContain('参考，不计入差额'); expect(csv).toContain('"PHP","","\'-20');
  });
});
