import {expect,it,vi} from 'vitest';
const request=vi.hoisted(()=>vi.fn());
vi.mock('../src/api/request',()=>({requestApi:request,fetchApiFile:vi.fn()}));
import {fetchFinanceSourceFlows,fetchFinanceSourceFlowDetail,fetchFinanceSummaryTable,fetchFinanceSummaryDetail} from '../src/api/financeReconciliation';
it('原始流水为独立只读接口，携带取消信号且不回退模拟数据',()=>{
 const signal=new AbortController().signal;fetchFinanceSourceFlows({start:'2026-10-01',end:'2026-10-31'}, {signal});
 expect(request).toHaveBeenLastCalledWith(expect.objectContaining({method:'get',url:'/api/finance/summary/source-flows/',signal,noMockFallback:true,timeout:30000}));
 fetchFinanceSourceFlowDetail('warehouse','2',{signal});
 expect(request).toHaveBeenLastCalledWith(expect.objectContaining({method:'get',url:'/api/finance/summary/source-flows/warehouse/2/',signal,noMockFallback:true}));
});
it('无有效批次时汇总及构成调用独立只读查询，保留取消信号',()=>{
 const signal=new AbortController().signal;
 fetchFinanceSummaryTable(null,{filter_month:'2026-10'},{signal});
 expect(request).toHaveBeenLastCalledWith(expect.objectContaining({method:'get',url:'/api/finance/summary/query/',signal,noMockFallback:true}));
 fetchFinanceSummaryDetail(null,{query_context:12,row_key:'test',kind:'sales'},{signal});
 expect(request).toHaveBeenLastCalledWith(expect.objectContaining({method:'get',url:'/api/finance/summary/query-detail/',signal,noMockFallback:true,params:expect.objectContaining({query_context:12})}));
});
