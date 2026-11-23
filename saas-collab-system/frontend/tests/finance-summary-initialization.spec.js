import { expect, it, vi, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { execFileSync } from 'node:child_process';
import Initialization from '../src/views/finance/FinanceSummaryInitialization.vue';
const api=vi.hoisted(()=>vi.fn());
vi.mock('../src/api/request',()=>({requestApi:api}));
afterEach(()=>{vi.useRealTimers();vi.clearAllMocks();document.body.innerHTML='';});
const state={runtime:{ready:true},can_edit:true,scope_stores:[{id:41,code:'SPKJ1PH1'},{id:42,code:'SPKJ2PH1'}]};
const candidate=(checks={})=>({dataset:8,source:{database_scope:{stores:[41],from:'2026-10-01',to:'2026-10-31'},reconciliation:{conservation_passed:true,attribution_complete:true},source_checks:{coverage_complete:true,coverage:[],...checks}}});
const response=result=>({success:true,data:{pending:false,job:{id:1,status:'ready',finished_at:'2026-11-01T00:00:00Z'},result}});
it('恢复候选、恢复实际范围与时间；只有三项检查全通过才允许发布',async()=>{
 api.mockResolvedValue(response(candidate()));const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:1,scope:{stores:[41],from:'2026-10-01',to:'2026-10-31'}}}}});await flushPromises();
 expect(w.text()).toContain('SPKJ1PH1');expect(w.text()).toContain('2026-10-01');expect(w.text()).not.toContain('—');
 const publish=w.findAll('button').find(b=>b.text()==='确认发布候选批次');expect(publish.attributes('disabled')).toBeDefined();
 await w.find('input[type=checkbox]').setValue(true);api.mockResolvedValue({success:true,data:{dataset:8}});await publish.trigger('click');await flushPromises();
 expect(api).toHaveBeenLastCalledWith(expect.objectContaining({method:'post',url:'/api/finance/summary/8/publish/',data:{confirm:true}}));expect(w.emitted('published')).toHaveLength(1);w.unmount();
});
it.each([{conservation_passed:false,attribution_complete:true,coverage_complete:true},{conservation_passed:true,attribution_complete:false,coverage_complete:true},{conservation_passed:true,attribution_complete:true,coverage_complete:false}])('拒绝未通过任一核对项的发布 %o',async checks=>{
 api.mockResolvedValue(response({...candidate(),source:{...candidate().source,reconciliation:{conservation_passed:checks.conservation_passed,attribution_complete:checks.attribution_complete},source_checks:{coverage_complete:checks.coverage_complete,coverage:[]}}}));const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:1}}}});await flushPromises();expect(w.findAll('button').find(b=>b.text()==='确认发布候选批次').attributes('disabled')).toBeDefined();expect(w.find('input[type=checkbox]').attributes('disabled')).toBeDefined();w.unmount();
});
it('缺失数量保持未知、分页十项，并映射来源处理路由',async()=>{
 const coverage=Array.from({length:12},(_,i)=>({store_id:41,kind:i===0?'warehouse_order':'other',status:'missing',rows:0}));api.mockResolvedValue(response(candidate({coverage_complete:false,coverage})));const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:1}}}});await flushPromises();await w.findAll('button').find(b=>b.text()==='查看来源缺项').trigger('click');
 expect(w.text()).toContain('未获取，数量未知');expect(w.findAll('table')[1].findAll('tr')).toHaveLength(11);expect(w.get('a').attributes('href')).toBe('/finance/warehouse-fees');expect(w.find('.el-pagination').exists()).toBe(true);await w.findAll('.el-pager li').find(item=>item.text()==='2').trigger('click');await flushPromises();expect(w.findAll('table')[1].findAll('tr')).toHaveLength(3);await w.findAll('button').find(b=>b.text()==='收起来源缺项').trigger('click');expect(w.find('.el-pagination').exists()).toBe(false);w.unmount();
});
it('依赖缺失时禁用试算且日期不得超出今天',()=>{
 const w=mount(Initialization,{props:{state:{...state,runtime:{ready:false,missing:['node','private_storage']}}}});expect(w.text()).toContain('计算运行时');expect(w.text()).toContain('持久化批次存储');expect(w.find('button[type=submit]').attributes('disabled')).toBeDefined();expect(w.find('.el-date-editor--daterange').exists()).toBe(true);expect(api).not.toHaveBeenCalled();w.unmount();
});
it('提交范围无效时不发请求，且只允许授权店铺',async()=>{
 const w=mount(Initialization,{props:{state}});await w.get('form').trigger('submit');await flushPromises();expect(api).not.toHaveBeenCalled();expect(w.findComponent({name:'ElSelect'}).exists()).toBe(true);expect(w.findAllComponents({name:'ElOption'})).toHaveLength(2);w.unmount();
});
it('真实可搜索多选跨筛选保留先前选择的授权店铺ID',async()=>{
 const w=mount(Initialization,{props:{state},attachTo:document.body});await w.find('.el-select__wrapper').trigger('click');await flushPromises();let options=[...document.body.querySelectorAll('.el-select-dropdown__item')];await options.find(o=>o.textContent.includes('SPKJ1PH1')).click();await flushPromises();
 const input=w.get('.el-select__input');await input.setValue('SPKJ2');await flushPromises();options=[...document.body.querySelectorAll('.el-select-dropdown__item')];await options.find(o=>o.textContent.includes('SPKJ2PH1')).click();await flushPromises();expect(w.findComponent({name:'ElSelect'}).props('modelValue')).toEqual([41,42]);w.unmount();
});
it('恢复scope只在两个日期均存在时恢复账期；按浏览器本地日期禁选未来日期',async()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-11-23T16:30:00.000Z'));api.mockResolvedValue({success:true,data:{pending:false,job:{id:1,status:'failed'}}});const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:1,scope:{stores:[41],from:'2026-01-01'}}}}});await flushPromises();expect(w.find('.el-date-editor--daterange input').element.value).toBe('');
 const disabledDate=w.findComponent({name:'ElDatePicker'}).props('disabledDate');const today=new Date();const tomorrow=new Date();tomorrow.setDate(tomorrow.getDate()+1);expect(disabledDate(today)).toBe(false);expect(disabledDate(tomorrow)).toBe(true);w.unmount();
});
it('日期限制在上海跨午夜动态更新，曼谷浏览器仍按本地日判断',()=>{
 const w=mount(Initialization,{props:{state}});const disabled=w.findComponent({name:'ElDatePicker'}).props('disabledDate').toString();w.unmount();
 const script=`const NativeDate=Date;let sampled;globalThis.Date=class extends NativeDate{constructor(...args){super(...(args.length?args:[sampled]));}};const disabled=${disabled};const run=when=>{sampled=when;return disabled(new NativeDate(2026,10,24));};console.log(JSON.stringify([run('2026-11-23T15:59:59Z'),run('2026-11-23T16:00:01Z')]));`;
 for(const [zone,expected] of [['Asia/Shanghai',[true,false]],['Asia/Bangkok',[true,true]]]){
  const actual=JSON.parse(execFileSync(process.execPath,['-e',script],{encoding:'utf8',env:{...process.env,TZ:zone}}));expect(actual).toEqual(expected);
 }
});
it('排队任务轮询到ready，结果scope优先覆盖任务scope',async()=>{
 vi.useFakeTimers();api.mockResolvedValueOnce({success:true,data:{pending:true,job:{id:9,status:'queued'}}}).mockResolvedValueOnce({success:true,data:{pending:true,job:{id:9,status:'running'}}}).mockResolvedValueOnce(response(candidate()));const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:9,scope:{stores:[41],from:'2026-01-01',to:'2026-01-31'}}}}});await flushPromises();await vi.advanceTimersByTimeAsync(3000);await vi.advanceTimersByTimeAsync(3000);await flushPromises();expect(api).toHaveBeenCalledTimes(3);expect(w.text()).toContain('2026-10-01');expect(w.text()).toContain('SPKJ1PH1');w.unmount();
});
it('重新计算失败时保留旧候选而清空进度与确认',async()=>{
 api.mockResolvedValueOnce(response(candidate()));const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:10,scope:{stores:[41],from:'2026-01-01',to:'2026-01-31'}}}}});await flushPromises();api.mockResolvedValueOnce({success:false,message:'重算失败'});await w.get('form').trigger('submit');await flushPromises();expect(w.text()).toContain('候选试算 #8');expect(w.text()).toContain('重算失败');expect(w.text()).not.toContain('正在读取来源');w.unmount();
});
it.each(['failed','superseded'])('任务终态 %s 显示错误且不改成候选',async status=>{
 api.mockResolvedValue({success:true,data:{pending:false,job:{id:2,status}}});const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:2}}}});await flushPromises();expect(w.find('[aria-label="候选试算核对"]').exists()).toBe(false);expect(w.find('[role="alert"]').exists()).toBe(true);w.unmount();
});
it('卸载后不再发出下一次轮询请求',async()=>{
 vi.useFakeTimers();api.mockResolvedValue({success:true,data:{pending:true,job:{id:3,status:'queued'}}});const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:3}}}});await flushPromises();expect(api).toHaveBeenCalledTimes(1);w.unmount();await vi.advanceTimersByTimeAsync(3000);expect(api).toHaveBeenCalledTimes(1);
});
it('15分钟轮询超时保留任务状态并给出提示',async()=>{
 vi.useFakeTimers();api.mockResolvedValue({success:true,data:{pending:true,job:{id:4,status:'running'}}});const w=mount(Initialization,{props:{state:{...state,initialization_job:{id:4}}}});await flushPromises();await vi.advanceTimersByTimeAsync(903000);await flushPromises();expect(w.text()).toContain('等待超过15分钟');expect(api.mock.calls.length).toBeGreaterThan(200);w.unmount();
});
