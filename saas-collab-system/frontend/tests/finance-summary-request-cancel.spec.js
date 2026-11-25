import { expect, it, vi } from 'vitest';
const request=vi.hoisted(()=>vi.fn());
vi.mock('../src/api/request',()=>({requestApi:request,fetchApiFile:vi.fn()}));
import { fetchFinanceSummaryTable, fetchFinanceSummaryDetail, fetchFinanceSummaryHistory, fetchFinanceSummaryJob, fetchFinanceSummary, fetchFinanceSummaryDocument } from '../src/api/financeReconciliation';
it.each([fetchFinanceSummaryTable,fetchFinanceSummaryDetail,fetchFinanceSummaryHistory])('财务读取将取消信号传给HTTP配置，不混入查询参数：%s',call=>{
 const controller=new AbortController(),params={page:1};call(1,params,{signal:controller.signal});
 expect(request).toHaveBeenLastCalledWith(expect.objectContaining({method:'get',params,signal:controller.signal}));
 controller.abort();expect(request.mock.calls.at(-1)[0].signal.aborted).toBe(true);
});
it('状态读取透传取消信号，旧调用保持兼容',()=>{
 const controller=new AbortController();fetchFinanceSummaryJob(9,{signal:controller.signal});expect(request).toHaveBeenLastCalledWith(expect.objectContaining({url:'/api/finance/summary/jobs/9/',signal:controller.signal}));
 expect(()=>fetchFinanceSummaryJob(9)).not.toThrow();expect(()=>fetchFinanceSummaryTable(1,{page:1})).not.toThrow();
});

it('元数据与文档读取均透传取消信号',async()=>{
 const controller=new AbortController();fetchFinanceSummary({native:1},{signal:controller.signal});expect(request).toHaveBeenLastCalledWith(expect.objectContaining({signal:controller.signal,params:{native:1}}));
 const {fetchApiFile}=await import('../src/api/request');fetchFinanceSummaryDocument(1,{toolsOnly:true,signal:controller.signal});expect(fetchApiFile).toHaveBeenLastCalledWith('/api/finance/summary/1/document/?tools=1',{timeout:120000,signal:controller.signal});
});
