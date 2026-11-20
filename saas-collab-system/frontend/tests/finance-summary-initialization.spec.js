import { expect, it, vi, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import Initialization from '../src/views/finance/FinanceSummaryInitialization.vue';
const api=vi.hoisted(()=>vi.fn());
vi.mock('../src/api/request',()=>({requestApi:api}));
afterEach(()=>vi.clearAllMocks());
const state={runtime:{ready:true},can_edit:true,scope_stores:[{id:41,code:'SPKJ1PH1'}]};
const candidate={dataset:8,source:{database_scope:{from:'2026-10-01',to:'2026-10-31'},reconciliation:{conservation_passed:true,attribution_complete:false},source_checks:{coverage_complete:false,coverage:[{store_id:41,kind:'warehouse_order',status:'missing'}]}}};
it('恢复候选只显示核对结果，未经确认不发布',async()=>{
 api.mockResolvedValue({success:true,data:{pending:false,job:{id:1,status:'ready'},result:candidate}});
 const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:1}}}});await flushPromises();
 expect(w.text()).toContain('尚未发布');expect(w.text()).toContain('不按零费用处理');
 const publish=w.findAll('button').find(b=>b.text()==='确认发布候选批次');
 expect(publish.attributes('disabled')).toBeDefined();expect(api).toHaveBeenCalledTimes(1);
 await w.find('input[type=checkbox]').setValue(true);api.mockResolvedValue({success:true,data:{dataset:8}});
 await publish.trigger('click');await flushPromises();
 expect(api).toHaveBeenLastCalledWith(expect.objectContaining({method:'post',url:'/api/finance/summary/8/publish/',data:{confirm:true}}));
 expect(w.emitted('published')).toHaveLength(1);w.unmount();
});
it('依赖缺失时禁用试算，并显示具体缺项',()=>{
 const w=mount(Initialization,{props:{state:{...state,runtime:{ready:false,missing:['node','private_storage']}}}});
 expect(w.text()).toContain('计算运行时');expect(w.text()).toContain('持久化批次存储');
 expect(w.find('button').attributes('disabled')).toBeDefined();expect(api).not.toHaveBeenCalled();w.unmount();
});
