import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
const api=vi.hoisted(()=>Object.fromEntries(['fetchFinanceSummary','fetchFinanceSummaryJob','rebuildFinanceSummary','fetchFinanceSummaryTable','fetchFinanceSummaryDetail','saveFinanceSummaryFee','fetchFinanceSummaryHistory','fetchFinanceSummaryDocument','fetchFinanceSourceFlows','fetchFinanceSourceFlowDetail'].map(k=>[k,vi.fn()])));
vi.mock('../src/api/financeReconciliation',()=>api);
import Summary from '../src/views/finance/FinanceSummaryNative.vue';
const good=data=>({success:true,data});
const batch=()=>({dataset:1,tenant_id:'test-tenant',label:'验收批次',revision:0,can_edit:true,source:{database_scope:{stores:[58],from:'2026-09-01',to:'2026-09-30'}}});
const row=()=>({key:'shop',identity:{country:'泰国',platform:'shopee',store:'58',shop:'SP6TH',currency:'THB'},values:{sales:'119410.000000',order_fee:'-29626.000000'},partial:{},profits:{operations:'100.000000',finance:null},rates:{order_fee:'-24.81%'},pending:true});
const table=()=>({rows:[row()],total:41,page:1,revision:0,options:{stores:[{id:'58',code:'SP6TH',country:'TH',platform:'shopee',currency:'THB'}],countries:{TH:'泰国'},months:['2026-09'],kinds:[{key:'order_fee',label:'订单费用'}]},rate_fields:[['order_fee','订单费用率']]});
const render=()=>mount(Summary,{global:{stubs:{'el-alert':{props:['title'],template:'<p>{{title}}</p>'},'el-dialog':{name:'ElDialog',props:['modelValue','title'],template:'<div v-if="modelValue"><slot /></div>'},'el-drawer':{name:'ElDrawer',props:['modelValue','title'],template:'<div v-if="modelValue"><slot /></div>'}}}});
async function publishedFlow(w){if(w.find('[data-flow-mode="summary"]').exists())await w.find('[data-flow-mode="summary"]').trigger('click');}
const picker=w=>w.findComponent({name:'FinancePeriodPicker'});
const chosenPeriod=w=>picker(w).props('modelValue');
async function openPeriod(w){await w.find('.period-trigger').trigger('click');}
async function applyPeriod(w){await w.find('.apply-period').trigger('click');}
async function chooseDimension(w,type){await openPeriod(w);await w.findAll('.period-dimensions button').find(b=>b.text()===({month:'月度',week:'周度',half_month:'半月'})[type]).trigger('click');await applyPeriod(w);}
async function navigatePeriod(w,month){const title=w.find('.period-calendar header strong').text(),parts=title.match(/(\d+)年(?:(\d+)月)?/),week=!!parts[2],delta=week?(Number(month.slice(0,4))-Number(parts[1]))*12+Number(month.slice(5))-Number(parts[2]):Number(month.slice(0,4))-Number(parts[1]);for(let i=0;i<Math.abs(delta);i++)await w.find('[aria-label="'+(delta<0?'上':'下')+(week?'个月':'一年')+'"]').trigger('click');}
async function chooseMonth(w,month){await openPeriod(w);if(!month){await w.findAll('.period-dimensions button').find(b=>b.text()==='全部账期').trigger('click');}else{await navigatePeriod(w,month);const type=chosenPeriod(w).period_type;const selector=type==='month'?'[data-month="'+month+'"]':type==='half_month'?'[data-half="'+month+'-16"]':'[data-day="'+month+'-'+new Date(Date.UTC(Number(month.slice(0,4)),Number(month.slice(5)),0)).getUTCDate()+'"]';await w.find(selector).trigger('click');}await applyPeriod(w);}
async function chooseInterval(w,value){await openPeriod(w);if(value==='undated')await w.findAll('.period-dimensions button').find(b=>b.text()==='待归期').trigger('click');else{await navigatePeriod(w,value.slice(0,7));await w.find('['+(chosenPeriod(w).period_type==='week'?'data-day':'data-half')+'="'+value+'"]').trigger('click');}await applyPeriod(w);}
beforeEach(()=>{vi.resetAllMocks();api.fetchFinanceSummary.mockResolvedValue(good(batch()));api.fetchFinanceSourceFlows.mockResolvedValue(good({rows:[],has_more:false,next_cursor:null,options:{...table().options,raw_flows:true}}));api.fetchFinanceSourceFlowDetail.mockResolvedValue(good({title:'原始流水来源',amount:'-1',parts:[]}));api.fetchFinanceSummaryTable.mockResolvedValue(good(table()));api.fetchFinanceSummaryDetail.mockResolvedValue(good({title:'费用构成',sales:'119410',amount:'-29626',parts:[{label:'佣金',amount:'-100',rate:'0.08%'}]}));api.fetchFinanceSummaryHistory.mockResolvedValue(good({rows:[],total:0,page:1}));});
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});
it('没有有效批次时直接查询汇总，刷新不打开候选试算或发布弹窗',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good({direct_query:true,dataset:null,revision:0,can_edit:false,scope_stores:[{id:41,code:'SPKJ1PH1',country_code:'PH'}]}));
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),query_context:12,source_read_at:'2026-11-25T00:00:00Z'}));
 const w=render();await flushPromises();
 expect(w.find('h1').text()).toBe('平台账单');expect(w.find('.summary-table tbody').text()).toContain('119,410.00');
 expect(api.fetchFinanceSummaryTable).toHaveBeenCalledWith(null,expect.objectContaining({view:'store'}),expect.anything());
 expect(w.text()).not.toContain('候选试算');expect(w.findComponent({name:'FinanceSummaryInitialization'}).exists()).toBe(false);
 await w.find('.page-heading .primary-action').trigger('click');await flushPromises();
 expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(null,expect.objectContaining({refresh:1}),expect.anything());
 expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();
 await w.find('tbody button').trigger('click');await flushPromises();
 expect(api.fetchFinanceSummaryDetail).toHaveBeenCalledWith(null,expect.objectContaining({query_context:12}),expect.anything());w.unmount();
});
it('只读用户无需写入权限即可查询，没有候选生成入口',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good({direct_query:true,dataset:null,revision:0,can_edit:false,scope_stores:[]}));
 const w=render();await flushPromises();expect(w.find('.scope-filters').exists()).toBe(true);
 expect(w.find('.page-heading .primary-action').attributes('disabled')).toBeUndefined();
 await w.find('.scope-filters').trigger('submit');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(2);
 expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();expect(w.text()).not.toContain('请联系');w.unmount();
});
it('直接汇总版本过期后仍读取直接查询元数据，不回到初始化流程',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good({direct_query:true,dataset:null,revision:0,can_edit:false,scope_stores:[]}));
 api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:false,job:{status:'superseded'}})).mockResolvedValue(good(table()));
 const w=render();await flushPromises();
 expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(2);
 expect(api.fetchFinanceSummary.mock.calls.every(([params])=>params.direct===1)).toBe(true);
 expect(w.find('.summary-table tbody').text()).toContain('119,410.00');
 expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();w.unmount();
});
it('无已发布批次时实时流水独立查询、游标翻页及来源下钻，不提交汇总任务',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good({initialized:false,can_edit:true,runtime:{ready:true},scope_stores:[{id:41,code:'SPKJ1PH1'}],initialization_job:{scope:{to:'2026-10-31'}}}));
 const raw={...row(),key:'finance-transaction:7',source_id:'finance-transaction:7',date:'2026-10-02',kind:'order_fee',label:'订单费用',original_amount:'-1.23',original_currency:'PHP',amount:null,mode_label:'原始记录（未分摊）',status:'已确认',editable:false};
 const source={rows:[raw],has_more:true,next_cursor:'cursor-2',options:{...table().options,raw_flows:true}};
 api.fetchFinanceSourceFlows.mockResolvedValueOnce(good(source)).mockResolvedValue(good({...source,has_more:false,next_cursor:null}));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();
 expect(api.fetchFinanceSourceFlows).toHaveBeenLastCalledWith(expect.objectContaining({start:'2026-10-01',end:'2026-10-31',page_size:50}),expect.objectContaining({signal:expect.any(AbortSignal)}));
 expect(w.find('.ledger-table tbody').text()).toContain('-1.23');expect(w.find('.ledger-table tbody').text()).toContain('未折算');
 expect(w.find('.count').text()).toBe('当前页 1 条原始记录');expect(w.find('.pagination').text()).toContain('第 1 页');
 await w.findAll('.pagination button')[1].trigger('click');await flushPromises();
 expect(api.fetchFinanceSourceFlows).toHaveBeenLastCalledWith(expect.objectContaining({cursor:'cursor-2'}),expect.anything());
 expect(w.find('.pagination').text()).toContain('第 2 页');expect(w.findAll('.pagination button')[1].attributes('disabled')).toBeDefined();
 await w.find('.ledger-table .actions button').trigger('click');await flushPromises();
 expect(api.fetchFinanceSourceFlowDetail).toHaveBeenLastCalledWith('finance-transaction','7',expect.objectContaining({signal:expect.any(AbortSignal)}));
 expect(api.fetchFinanceSummaryTable).not.toHaveBeenCalled();expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();w.unmount();
});
it('切换视图取消旧原始流水，迟到权限响应不清空新结果',async()=>{
 vi.useFakeTimers();
 let late;api.fetchFinanceSourceFlows.mockImplementationOnce(()=>new Promise(resolve=>late=resolve));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();
 const oldSignal=api.fetchFinanceSourceFlows.mock.calls[0][1].signal;
 await w.find('[data-view="store"]').trigger('click');await vi.advanceTimersByTimeAsync(250);await flushPromises();late({success:false,http_status:403,message:'old denied'});await flushPromises();
 expect(oldSignal.aborted).toBe(true);expect(w.find('.summary-table tbody').text()).toContain('SP6TH');expect(w.text()).not.toContain('old denied');w.unmount();
});
it('流水来源抽屉关闭后迟到权限错误不影响当前列表',async()=>{
 let late;api.fetchFinanceSourceFlowDetail.mockImplementation(()=>new Promise(resolve=>late=resolve));
 const raw={...row(),key:'warehouse:2',source_id:'warehouse:2',date:'2026-09',kind:'warehouse_order',label:'处理费',original_amount:'-2',original_currency:'CNY',amount:null};
 api.fetchFinanceSourceFlows.mockResolvedValue(good({rows:[raw],has_more:false,options:{...table().options,raw_flows:true}}));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();
 await w.find('.ledger-table .actions button').trigger('click');await flushPromises();
 const drawer=w.findAllComponents({name:'ElDrawer'}).find(c=>c.props('title')==='金额构成');drawer.vm.$emit('update:modelValue',false);await flushPromises();
 late({success:false,http_status:403,message:'closed denied'});await flushPromises();expect(w.find('.ledger-table tbody').text()).toContain('-2.00');expect(w.text()).not.toContain('closed denied');w.unmount();
});
it('无批次时离开流水页立即取消读取，不等待旧请求结束',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good({initialized:false,can_edit:true,runtime:{ready:true},scope_stores:[],initialization_job:{scope:{to:'2026-10-31'}}}));
 let late;api.fetchFinanceSourceFlows.mockImplementation(()=>new Promise(resolve=>late=resolve));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();
 const signal=api.fetchFinanceSourceFlows.mock.calls[0][1].signal;
 await w.find('[data-view="store"]').trigger('click');await flushPromises();
 expect(signal.aborted).toBe(true);expect(w.find('.query-progress small').exists()).toBe(false);
 late({success:false,http_status:403,message:'stale source denied'});await flushPromises();expect(w.text()).not.toContain('stale source denied');w.unmount();
});
it('旧批次未提供日期时，从实际月份列表选择最新账期',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good({...batch(),source:{}}));const data=table();data.options.months=['2026-08','2026-10'];api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
 const w=render();await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(2);expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_month:'2026-10'}),expect.objectContaining({signal:expect.any(AbortSignal)}));await chooseMonth(w,'');await w.find('.scope-filters').trigger('submit');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_month:''}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
});
it('周度默认区间按北京时间判断，不受浏览器UTC日期跨日影响',async()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-11-22T18:00:00Z'));api.fetchFinanceSummary.mockResolvedValue(good({...batch(),source:{database_scope:{stores:[58],from:'2026-11-01',to:'2026-11-24'}}}));
 const data=table();data.options.months=['2026-11'];data.options.periods_by_month={'2026-11':{week:[{value:'2026-11-23',label:'本周'},{value:'2026-11-16',label:'上周'}]}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));const w=render();await flushPromises();await chooseDimension(w,'week');await w.find('.scope-filters').trigger('submit');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period:'2026-11-23'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
});
it('已关账店铺的新增表单提前阻止提交，不等待后端报错',async()=>{
 const data=table();data.options.closed_periods=[{shop:'SP6TH',month:'2026-09'}];api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();await w.findAll('button').find(b=>b.text()==='人工新增记录').trigger('click');expect(w.find('.fee-form').text()).toContain('已关账');expect(w.find('.fee-form button[type="submit"]').attributes('disabled')).toBeDefined();await w.find('.fee-form').trigger('submit');expect(api.saveFinanceSummaryFee).not.toHaveBeenCalled();w.unmount();
});
it('流水区分原额与折算额，展示真实计入口径和汇率依据',async()=>{
 const flow={...row(),key:'fx:1',date:'2026-09-03',kind:'order_fee',amount:'-585.00',original_amount:'-10.00',original_currency:'USD',mode:'both',mode_label:'运营',status:'已纳入汇总',conversion:{from:'USD',to:'THB',rate:'58.5',basis:'日汇率',period:'2026-09-03'}};
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[flow],options:{...table().options,raw_flows:true}}));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();const cells=w.find('.ledger-table tbody tr').findAll('td');
 expect(cells[4].text()).toContain('-10.00 USD');expect(cells[5].text()).toContain('-585.00');expect(cells[5].find('[aria-label]').attributes('aria-label')).toContain('汇率 58.5');expect(cells[6].text()).toBe('运营');expect(w.text()).toContain('原币币种');w.unmount();
});
it('原始流水页提供人工新增与逐笔排除，提交只包含来源标识和原因',async()=>{
 const flow={...row(),key:'finance-transaction:1',source_id:'finance-transaction:1',date:'2026-09-03',kind:'order_fee',label:'订单费用',amount:'-12.00',original_amount:'-12.00',mode:'both',status:'正常',participation:{supported:true,excluded:false}};
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[flow],options:{...table().options,raw_flows:true}}));
 api.saveFinanceSummaryFee.mockResolvedValue(good({revision:1}));
 const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();
 expect(w.findAll('button').some(b=>b.text()==='人工新增记录')).toBe(true);
 await w.findAll('button').find(b=>b.text()==='排除汇总').trigger('click');await w.find('.fee-form textarea').setValue('重复来源，已核实');await w.find('.fee-form').trigger('submit');await flushPromises();
 expect(api.saveFinanceSummaryFee).toHaveBeenCalledWith(1,{revision:0,record:{id:'finance-transaction:1',operation:'exclude_source',reason:'重复来源，已核实'}});w.unmount();
});
it('字段异常标记携带具体原因，利润保留数值且标记可下钻',async()=>{
 const r=row();r.values.product_cost='0.000000';r.partial.product_cost=true;r.field_issues={product_cost:['SKU A 未维护采购成本'],profit_operations:['商品成本：SKU A 未维护采购成本']};
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[r]}));
 const w=render();await flushPromises();
 const markers=w.findAll('.field-anomaly');expect(markers.some(b=>b.attributes('aria-label').includes('SKU A 未维护采购成本'))).toBe(true);
 expect(w.find('.profit').text()).toContain('100.00');
 const costMarker=markers.find(b=>b.attributes('aria-label').startsWith('商品成本：'));
 await costMarker.trigger('click');await flushPromises();
 expect(api.fetchFinanceSummaryDetail).toHaveBeenLastCalledWith(1,expect.objectContaining({row_key:'shop',kind:'product_cost'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
 expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
});
it('负销售额费率不按费用金额重写符号，零分母显示数字及提示',async()=>{
 const r=row();r.values.sales='-100';r.values.order_fee='-25';r.rates.order_fee='25.00%';
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[r]}));
 let w=render();await flushPromises();await w.findAll('[aria-label="财务指标展示方式"] button')[1].trigger('click');expect(w.find('[data-field="order_fee"]').text()).toContain('25.00%');expect(w.find('[data-field="order_fee"]').text()).not.toContain('-25.00%');w.unmount();
 r.values.sales='0';r.rates.order_fee='0.00%';w=render();await flushPromises();await w.findAll('[aria-label="财务指标展示方式"] button')[1].trigger('click');expect(w.find('[data-field="order_fee"]').text()).toContain('0.00%');expect(w.find('[data-field="order_fee"] .field-anomaly').attributes('aria-label')).toContain('销售额为零');w.unmount();
});
const databaseBatch=(extra={})=>({...batch(),source:{database_scope:{stores:[58],from:'2026-09-01',to:'2026-09-30'},data_origin:'saas_database'},source_changed:false,...extra});
it('首屏选择已接入的最新月份，周度默认跳过尚未发生的末周',async()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-11-24T04:00:00Z'));
 api.fetchFinanceSummary.mockResolvedValue(good({...databaseBatch(),source:{database_scope:{from:'2026-10-01',to:'2026-11-24',stores:[58]}}}));
 const data=table();data.options.months=['2026-11','2026-10'];data.options.periods_by_month={'2026-11':{week:[{value:'2026-11-30',label:'尚未发生'},{value:'2026-11-23',label:'当前周'}]}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
 const w=render();await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_month:'2026-11'}),expect.objectContaining({signal:expect.any(AbortSignal)}));await chooseDimension(w,'week');await w.find('.scope-filters').trigger('submit');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period:'2026-11-23'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
});
it('首屏以筛选和汇总为主，来源、归属和长说明默认收起',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),period_note:'原字段及归属计算规则保持不变'}));
 const w=render();await flushPromises();
 for(const selector of ['.source-disclosure','.reconciliation-disclosure','.calculation-disclosure'])expect(w.find(selector).attributes('open')).toBeUndefined();
 expect(w.find('.filters').element.compareDocumentPosition(w.find('.view-bar').element)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(w.find('.result-toolbar [aria-label="财务指标展示方式"]').exists()).toBe(true);
 expect(w.find('[aria-label="汇总级别"]').findAll('button')).toHaveLength(6);
 await w.find('[data-attribution="pending"]').trigger('click');await flushPromises();
 expect(w.find('.reconciliation-disclosure').attributes('open')).toBeDefined();
 expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(2);w.unmount();
});
it('切换加载时清空旧数据和页数，不将上个视图的数量标成新视图',async()=>{
 const w=render();await flushPromises();let finish;
 api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>finish=resolve));
 await w.find('[data-view="sku"]').trigger('click');await flushPromises();
 expect(w.find('.count').text()).toBe('正在核对结果数量…');expect(w.find('.pagination').text()).toContain('— / —');expect(w.findAll('.summary-table tbody tr')).toHaveLength(0);
 finish(good({...table(),total:2}));await flushPromises();expect(w.find('.count').text()).toBe('2 组');w.unmount();
});
it.each(['ready','failed'])('账期标题从提交起就对应当前请求，完成状态为%s',async(outcome)=>{
 const data=table();data.options.months=['2026-09','2026-08'];api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
 const w=render();await flushPromises();expect(w.find('.result-context').text()).toContain('2026-09');
 let finish,fail;api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise((resolve,reject)=>{finish=resolve;fail=reject;}));
 await chooseMonth(w,'2026-08');await w.find('.scope-filters').trigger('submit');await flushPromises();
 expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_month:'2026-08'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
 expect(w.find('.result-context').text()).toContain('2026-08');expect(w.find('.result-context').text()).not.toContain('2026-09');
 expect(w.findAll('.summary-table tbody tr')).toHaveLength(0);expect(w.find('.count').text()).toBe('正在核对结果数量…');
 if(outcome==='ready')finish(good(data));else fail(Error('八月查询暂未完成'));
 await flushPromises();expect(w.find('.result-context').text()).toContain('2026-08');
 if(outcome==='failed'){expect(w.text()).toContain('八月查询暂未完成');expect(w.findAll('.summary-table tbody tr')).toHaveLength(0);}
 w.unmount();
});
it('账期加载中切换视图，旧请求晚返回不会覆盖当前标题和结果',async()=>{
 vi.useFakeTimers();
 const data=table();data.options.months=['2026-09','2026-08'];api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
 const w=render();await flushPromises();let stale,current;
 api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>stale=resolve)).mockImplementationOnce(()=>new Promise(resolve=>current=resolve));
 await chooseMonth(w,'2026-08');await w.find('.scope-filters').trigger('submit');await flushPromises();
 await w.find('[data-view="order"]').trigger('click');await flushPromises();
 expect(w.find('.result-context').text()).toContain('订单汇总 · 月度分摊 · 2026-08');
 await vi.advanceTimersByTimeAsync(200);await flushPromises();
 current(good({...data,rows:[{...row(),values:{sales:'500.00'}}]}));await flushPromises();
 stale(good(data));await flushPromises();
 expect(w.find('.result-context').text()).toContain('订单汇总 · 月度分摊 · 2026-08');
 expect(w.text()).toContain('500.00');expect(w.text()).not.toContain('119,410.00');w.unmount();
});
it('查询进行中连续切换只提交最后一个视图，标题即时更新且卸载取消待提交请求',async()=>{
 vi.useFakeTimers();const w=render();await flushPromises();let initial;
 api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>initial=resolve));
 await w.find('[data-view="order"]').trigger('click');await flushPromises();const submitted=api.fetchFinanceSummaryTable.mock.calls.length;
 await w.find('[data-view="sku"]').trigger('click');await w.find('[data-view="product_link"]').trigger('click');await flushPromises();
 expect(w.find('.result-context').text()).toContain('商品链接汇总');expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(submitted);
 await vi.advanceTimersByTimeAsync(199);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(submitted);
 await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(submitted+1);
 expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({view:'product_link',filter_month:'2026-09'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
 initial(good(table()));await flushPromises();expect(w.find('.result-context').text()).toContain('商品链接汇总');
 let pending;api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>pending=resolve));
 await w.find('[data-view="order"]').trigger('click');await flushPromises();await w.find('[data-view="sku"]').trigger('click');
 const beforeUnmount=api.fetchFinanceSummaryTable.mock.calls.length;w.unmount();await vi.advanceTimersByTimeAsync(1000);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(beforeUnmount);
 pending(good(table()));await flushPromises();
});
it('被替代的查询自动读取最新批次，保留筛选并只重试一次',async()=>{
 api.fetchFinanceSummary.mockResolvedValueOnce(good(batch())).mockResolvedValue(good({...batch(),dataset:2}));
 api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:false,job:{id:1,status:'superseded'}})).mockResolvedValue(good(table()));
 const w=render();await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(2,expect.objectContaining({filter_month:'2026-09'}),expect.objectContaining({signal:expect.any(AbortSignal)}));expect(w.find('.summary-status').exists()).toBe(false);expect(w.text()).toContain('119,410.00');w.unmount();
});
it('连续版本变更停止重试并显示可恢复错误',async()=>{
 api.fetchFinanceSummaryTable.mockResolvedValue(good({pending:false,job:{id:1,status:'superseded'}}));
 const w=render();await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(2);expect(w.find('.summary-status').text()).toContain('版本已变化');w.unmount();
});
it('整表默认金额，费率切换不发请求，结果分别展示且共用明细入口',async()=>{
 const r=row();r.values={...r.values,product_cost:'-60000',operations:'-10',finance:'-20'};r.profits={operations:'100',finance:'-50'};r.rates={...r.rates,gross_margin:'49.75%',operations:'-0.01%',finance:'-0.02%',profit_operations:'0.08%',profit_finance:'-0.04%'};
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[r]}));
 const w=render();await flushPromises();expect(w.find('[data-field="gross_margin"]').text()).toContain('59,410.00');expect(w.find('[data-field="order_fee"]').text()).toContain('-29,626.00');
 await w.findAll('[aria-label="财务指标展示方式"] button')[1].trigger('click');
 expect(w.find('[data-field="gross_margin"]').text()).toContain('49.75%');expect(w.find('[data-field="order_fee"]').text()).toContain('-24.81%');expect(w.find('[data-field="operations"]').text()).toContain('-0.01%');expect(w.find('[data-field="profit_finance"]').text()).toContain('-0.04%');
 expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);
 await w.find('[data-field="order_fee"] button').trigger('click');await flushPromises();expect(api.fetchFinanceSummaryDetail).toHaveBeenLastCalledWith(1,expect.objectContaining({kind:'rate:order_fee'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
});
it('统一筛选区在标签前，结果工具栏与表格一体，流水不显示费率开关',async()=>{
 const w=render();await flushPromises();
 expect(w.find('.scope-filters .finance-period-picker').exists()).toBe(true);
 expect(w.findAll('.scope-filters .period-trigger')).toHaveLength(1);
 expect(w.find('.table-workbench .result-toolbar').exists()).toBe(true);
 expect(w.findAll('.summary-table .metric-cell')).toHaveLength(3);
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[{...row(),date:'2026-09-05',kind:'order_fee',label:'订单费用',flow_type:'平台佣金',source_id:'flow:1',original_amount:'-10',original_currency:'CNY',amount:'-5',mode:'both',status:'正常',source:'平台流水'}]}));
 await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();
 expect(w.find('[aria-label="财务指标展示方式"]').exists()).toBe(false);
 expect(w.find('.flow-filters').exists()).toBe(true);
 expect(w.find('.ledger-table').text()).toContain('flow:1');expect(w.find('.ledger-table').text()).toContain('CNY');expect(w.find('.ledger-table').text()).toContain('平台佣金');w.unmount();
});
function autoPolling(){vi.useFakeTimers();vi.spyOn(document,'hidden','get').mockReturnValue(false);}
describe('平台账单按需查询',()=>{
 it('正式汇总与待归属明细分区，切换不改变账期，待归属不显示利润',async()=>{
  api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),attribution:{pending_rows:38,totals:[{country:'菲律宾',label:'订单调整',currency:'PHP',mode:'operations',total:'-9',assigned:'0',pending:'-9'}]}}));
  const w=render();await flushPromises();expect(w.find('[aria-label="费用归属"]').text()).toContain('38');expect(w.text()).toContain('原额');
  await w.find('[data-attribution="pending"]').trigger('click');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({view:'detail',filter_attribution:'pending',filter_month:'2026-09'}),expect.objectContaining({signal:expect.any(AbortSignal)}));expect(w.find('.summary-table').exists()).toBe(false);
  await w.find('[data-view="sku"]').trigger('click');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({view:'sku',filter_attribution:'assigned'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
 });
 it('统计周期是六个汇总页的父级，周期查询后应用且局部重置不改变周期',async()=>{
  const data=table();data.options.periods_by_month={'2026-09':{week:[{value:'2026-09-14',label:'2026-09-14 — 2026-09-20'}]}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
  const w=render();await flushPromises();const context=w.find('[aria-label="统计周期"]');
  expect(context.exists()).toBe(true);expect(context.element.compareDocumentPosition(w.find('[aria-label="汇总级别"]').element)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(w.find('.scope-filters [aria-label="统计周期"]').exists()).toBe(true);expect(w.findAll('.period-trigger')).toHaveLength(1);
  await chooseDimension(w,'week');await w.find('.scope-filters').trigger('submit');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period_type:'week',filter_period:'2026-09-28'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
  expect(chosenPeriod(w).period_type).toBe('week');
  await w.find('[data-view="order"]').trigger('click');await flushPromises();await w.find('.filters input').setValue('test-order');await w.findAll('.filters button').find(b=>b.text()==='重置').trigger('click');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({view:'order',filter_order:'',filter_period_type:'week',filter_period:'2026-09-28'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
 });
 it('跨来源范围的周期显示已载入部分提示，不冒充完整周',async()=>{api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),period_warning:'本周期超出已接入范围，仅计算已载入部分'}));const w=render();await flushPromises();expect(w.text()).toContain('仅计算已载入部分');w.unmount();});
 it('周期与局部条件暂存后统一查询，不提交中间状态',async()=>{
  const data=table();data.options.months=['2026-09','2026-08'];data.options.periods_by_month={'2026-09':{week:[{value:'2026-09-14',label:'9月第三周'}]},'2026-08':{week:[{value:'2026-08-10',label:'8月第三周'},{value:'2026-08-03',label:'8月第二周'}]}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
  const w=render();await flushPromises();await w.find('[data-view="order"]').trigger('click');await flushPromises();const calls=api.fetchFinanceSummaryTable.mock.calls.length;await w.find('.filters input').setValue('尚未查询');await chooseDimension(w,'week');await chooseMonth(w,'2026-08');await chooseInterval(w,'2026-08-03');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(calls);
  await w.find('.scope-filters').trigger('submit');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_month:'2026-08',filter_period:'2026-08-03',filter_order:'尚未查询'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
 });
 it('周／半月参数传给服务端，切换SKU和链接不丢失统计区间',async()=>{
  const data=table();data.options.periods_by_month={'2026-09':{week:[{value:'2026-09-14',label:'2026-09-14 — 2026-09-20'}],half_month:[{value:'2026-09-16',label:'2026-09-16 — 2026-09-30'}]}};data.period_note='广告按所选粒度分摊';api.fetchFinanceSummaryTable.mockResolvedValue(good(data));
  const w=render();await flushPromises();
  await chooseDimension(w,'week');await w.find('.scope-filters').trigger('submit');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period_type:'week',filter_period:'2026-09-28'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
  await w.find('[data-view="sku"]').trigger('click');await flushPromises();await w.find('[data-view="product_link"]').trigger('click');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({view:'product_link',filter_period_type:'week',filter_period:'2026-09-28'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
  await chooseDimension(w,'half_month');await w.find('.scope-filters').trigger('submit');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period_type:'half_month',filter_period:'2026-09-16'}),expect.objectContaining({signal:expect.any(AbortSignal)}));expect(w.text()).toContain('半月分摊');
  w.unmount();
 });
 it('待归期可单独选择查询，回月度清除区间',async()=>{
  const w=render();await flushPromises();await chooseDimension(w,'week');await chooseInterval(w,'undated');await w.find('.scope-filters').trigger('submit');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period:'undated'}),expect.objectContaining({signal:expect.any(AbortSignal)}));await chooseDimension(w,'month');await w.find('.scope-filters').trigger('submit');await flushPromises();
  expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period_type:'month',filter_period:''}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
 });
 it('修改费用沿用财务日期，不把缺失的流水日期或揽收日期写回账务',async()=>{api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[{...row(),date:'2026-08-18',accounting_date:'2026-09-20',accounting_month:'2026-09',kind:'warehouse_order',mode:'both',amount:'-10',original_amount:'-10',editable:true,status:'正常'}]}));const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();await w.findAll('button').find(b=>b.text()==='修改').trigger('click');await flushPromises();expect(w.find('.fee-form input[type="month"]').element.value).toBe('2026-09');expect(w.find('.fee-form input[type="date"]').element.value).toBe('2026-09-20');w.unmount();});
 it('发货日期待补齐时展示服务端提示，切换结果不保留旧提示',async()=>{api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({...table(),date_warning:'59笔出库处理费缺少发货日期，保留原账期'}));const w=render();await flushPromises();expect(w.text()).toContain('59笔出库处理费缺少发货日期');await w.find('form').trigger('submit');await flushPromises();expect(w.text()).not.toContain('59笔出库处理费缺少发货日期');w.unmount();});
 it('冷查询排队后轮询持久结果，卸载停止轮询',async()=>{autoPolling();api.fetchFinanceSummaryTable.mockResolvedValue(good({pending:true,job:{id:7,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValueOnce(good({pending:true,job:{id:7,status:'running'}})).mockResolvedValueOnce(good({pending:false,job:{id:7,status:'ready'},result:table()}));const w=render();await flushPromises();expect(w.text()).toContain('后台任务排队中');await vi.advanceTimersByTimeAsync(300);await flushPromises();expect(w.text()).toContain('后台正在计算并校验');await vi.advanceTimersByTimeAsync(750);await flushPromises();expect(w.text()).toContain('119,410.00');expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(2);});
 it.each([['CALCULATOR_BUSY','queued',true,'计算资源正忙，任务将在后台自动重试'],['CALCULATOR_TIMEOUT','failed',false,'财务计算超过120秒']])('区分资源等待与计算超时：%s',async(error_code,status,pending,message)=>{
  autoPolling();api.fetchFinanceSummaryTable.mockResolvedValue(good({pending,job:{id:70,status,error_code}}));
  const w=render();await flushPromises();expect(w.text()).toContain(message);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
 });
 it('异步重算失败保留原金额，不重复提交',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));api.rebuildFinanceSummary.mockResolvedValue(good({pending:true,job:{id:8,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValue(good({pending:false,job:{id:8,status:'failed'}}));const w=render();await flushPromises();const button=w.findAll('button').find(b=>b.text()==='更新汇总');await button.trigger('click');await flushPromises();expect(button.attributes('disabled')).toBeDefined();expect(w.text()).toContain('当前保留上次汇总结果');expect(w.text()).toContain('119,410.00');await vi.advanceTimersByTimeAsync(5000);await flushPromises();expect(w.text()).toContain('后台计算失败');expect(w.text()).toContain('119,410.00');expect(api.rebuildFinanceSummary).toHaveBeenCalledTimes(1);w.unmount();});
 it('卸载未完成查询会取消等待计时器',async()=>{autoPolling();api.fetchFinanceSummaryTable.mockResolvedValue(good({pending:true,job:{id:9,status:'queued'}}));const w=render();await flushPromises();w.unmount();await vi.advanceTimersByTimeAsync(5000);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();});
 it('轮询发现权限失效时清空已有财务结果',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));api.rebuildFinanceSummary.mockResolvedValue(good({pending:true,job:{id:10,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValue({success:false,http_status:403,message:'访问权限已失效'});const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='更新汇总').trigger('click');await flushPromises();await vi.advanceTimersByTimeAsync(5000);await flushPromises();expect(w.text()).toContain('访问权限已失效');expect(w.text()).not.toContain('119,410.00');w.unmount();});
 it('打开页面发现来源变化自动重算，并保留版本和设置传递',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({source_changed:true,revision:3})));api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),revision:3}));api.rebuildFinanceSummary.mockResolvedValue(good(databaseBatch({dataset:2})));const w=render();await flushPromises();expect(api.rebuildFinanceSummary).toHaveBeenCalledExactlyOnceWith(1,3);expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(2,expect.objectContaining({view:'store'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();});
 it('来源不变仅检测，变化后自动重算并保留页码和筛选',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();await chooseMonth(w,'2026-09');await w.find('.scope-filters').trigger('submit');await w.find('form').trigger('submit');await flushPromises();api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),page:2}));await w.findAll('.pagination button')[1].trigger('click');await flushPromises();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({source_changed:true})));let finish;api.rebuildFinanceSummary.mockImplementation(()=>new Promise(r=>finish=r));await vi.advanceTimersByTimeAsync(60000);await flushPromises();expect(api.rebuildFinanceSummary).toHaveBeenCalledTimes(1);finish(good(databaseBatch({dataset:2})));await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(2,expect.objectContaining({page:2,filter_month:'2026-09'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();await vi.advanceTimersByTimeAsync(60000);expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(3);});
 it('编辑费用期间不检测，隐藏页面也暂停',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));const w=render();await flushPromises();await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();await w.findAll('button').find(b=>b.text()==='人工新增记录').trigger('click');await vi.advanceTimersByTimeAsync(30000);expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(1);await w.findAll('button').find(b=>b.text()==='取消').trigger('click');vi.spyOn(document,'hidden','get').mockReturnValue(true);await vi.advanceTimersByTimeAsync(30000);expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(1);w.unmount();});
 it('自动重算失败保留金额并在下一轮重试',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({source_changed:true})));api.rebuildFinanceSummary.mockRejectedValueOnce(new Error('来源变更')).mockResolvedValueOnce(good(databaseBatch({dataset:2})));const w=render();await flushPromises();expect(w.text()).toContain('自动汇总未完成');expect(w.text()).toContain('119,410.00');await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.rebuildFinanceSummary).toHaveBeenCalledTimes(2);expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(2,expect.anything(),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();});
 it('只读用户只跟随新批次，不触发重算',async()=>{autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({can_edit:false,source_changed:true})));const w=render();await flushPromises();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({dataset:2,can_edit:false})));await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(2,expect.anything(),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();});
 it('数据库批次重新汇总后查询新批次，处理中禁止重复提交',async()=>{api.fetchFinanceSummary.mockResolvedValue(good({...batch(),source:{database_scope:{stores:[58]},data_origin:'saas_database'}}));let finish;api.rebuildFinanceSummary.mockImplementation(()=>new Promise(resolve=>finish=resolve));const w=render();await flushPromises();const button=w.findAll('button').find(b=>b.text()==='更新汇总');await button.trigger('click');expect(api.rebuildFinanceSummary).toHaveBeenCalledWith(1,0);expect(button.attributes('disabled')).toBeDefined();expect(w.text()).toContain('正在读取SaaS数据');finish(good({...batch(),dataset:2,source:{database_scope:{stores:[58]},data_origin:'saas_database'}}));await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(2,expect.objectContaining({page:1}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();});
 it('重新汇总失败保留原批次结果',async()=>{api.fetchFinanceSummary.mockResolvedValue(good({...batch(),source:{database_scope:{stores:[58]}}}));api.rebuildFinanceSummary.mockRejectedValue(new Error('来源发生变化，请重试'));const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='更新汇总').trigger('click');await flushPromises();expect(w.text()).toContain('来源发生变化');expect(w.text()).toContain('119,410.00');w.unmount();});
 it('首屏只取轻量元数据和当前页，不读取HTML整批',async()=>{const w=render();await flushPromises();expect(api.fetchFinanceSummary).toHaveBeenCalledWith({native:1,direct:1},expect.objectContaining({signal:expect.any(AbortSignal)}));expect(api.fetchFinanceSummaryTable).toHaveBeenCalledWith(1,expect.objectContaining({view:'store',page:1,page_size:20}),expect.objectContaining({signal:expect.any(AbortSignal)}));expect(api.fetchFinanceSummaryDocument).not.toHaveBeenCalled();expect(w.find('iframe').exists()).toBe(false);expect(w.text()).toContain('119,410.00');expect(w.text()).toContain('-29,626.00');w.unmount();});
 it('分页在服务端执行，切页不重取批次及快照',async()=>{const w=render();await flushPromises();await w.findAll('.pagination button')[1].trigger('click');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({page:2}),expect.objectContaining({signal:expect.any(AbortSignal)}));expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(1);w.unmount();});
 it('页签切换后筛选相应字段，旧响应不会覆盖当前页签',async()=>{vi.useFakeTimers();const w=render();await flushPromises();let resolve;api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(r=>resolve=r));await w.find('[data-view="sku"]').trigger('click');await w.find('[data-view="product_link"]').trigger('click');await flushPromises();await vi.advanceTimersByTimeAsync(200);await flushPromises();resolve(good({...table(),rows:[],total:0}));await flushPromises();expect(w.text()).toContain('商品名称／商品ID');expect(w.findAll('tbody tr')).toHaveLength(1);w.unmount();});
 it('金额构成按点击延迟请求且分母来自本行销售额',async()=>{const w=render();await flushPromises();expect(api.fetchFinanceSummaryDetail).not.toHaveBeenCalled();await w.find('tbody button').trigger('click');await flushPromises();expect(api.fetchFinanceSummaryDetail).toHaveBeenCalledWith(1,expect.objectContaining({row_key:'shop',kind:'sales'}),expect.objectContaining({signal:expect.any(AbortSignal)}));expect(w.text()).toContain('本行订单销售额：119,410.00');w.unmount();});
 it('只读账户不显示费用写入入口，读取失败清空旧结果',async()=>{api.fetchFinanceSummary.mockResolvedValue(good({...batch(),can_edit:false}));const w=render();await flushPromises();api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),view:'detail',rows:[]}));await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();expect(w.findAll('button').some(b=>b.text()==='人工新增记录')).toBe(false);api.fetchFinanceSummaryTable.mockResolvedValueOnce({success:false,message:'权限已变化'});await w.find('form').trigger('submit');await flushPromises();expect(w.text()).toContain('权限已变化');expect(w.findAll('tbody tr')).toHaveLength(0);w.unmount();});
});

it('缺失批次文件暂停计算并隐藏误导性空表，恢复后可重新检查',async()=>{
 autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({source_available:false,source_changed:true})));
 const w=render();await flushPromises();expect(w.text()).toContain('自动汇总已暂停');expect(w.find('.summary-table').exists()).toBe(false);
 await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.fetchFinanceSummaryTable).not.toHaveBeenCalled();expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();
 api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({source_available:true})));
 await w.findAll('button').find(b=>b.text()==='重新检查').trigger('click');await flushPromises();expect(w.text()).toContain('119,410.00');expect(w.find('.summary-status').exists()).toBe(false);w.unmount();
});
it('服务端调度模式不由浏览器重复提交重算',async()=>{
 autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({automation:{mode:'server'},source_changed:true})));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(31000);await flushPromises();
 expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();expect(w.text()).toContain('仅自动更新本月和上月');expect(w.text()).toContain('历史账期保留原结果');w.unmount();
});
it('范围修改明确提交，取消不改变汇总',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({source:{database_scope:{from:'2026-08-01',to:'2026-09-30',stores:[58]}},scope_stores:[{id:58,code:'SP6TH'}],automation:{mode:'server'}})));
 const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='汇总范围').trigger('click');
 expect(w.findAll('input[type="date"]')).toHaveLength(2);await w.findAll('input[type="date"]')[0].setValue('2026-07-01');
 api.rebuildFinanceSummary.mockResolvedValue(good(batch()));await w.find('form.fee-form').trigger('submit');await flushPromises();
 expect(api.rebuildFinanceSummary).toHaveBeenCalledWith(1,0,{from:'2026-07-01',to:'2026-09-30',stores:[58]});w.unmount();
});
it('待补日期入口保留账期并定位仓库处理费',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({automation:{mode:'server'}})));
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),date_warning:'缺少发货日期'}));
 const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='查看待补日期费用').trigger('click');await flushPromises();
 expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({view:'detail',filter_month:'2026-09',filter_kind:'warehouse_order',filter_status:'pending'}),expect.objectContaining({signal:expect.any(AbortSignal)}));w.unmount();
});

it('无流水的自动月份仍可筛选，历史月份保留且不触发重算',async()=>{
 api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch({automation:{mode:'server',scope:{from:'2026-10-01',to:'2026-11-14'}}})));
 const w=render();await flushPromises();
 const month=()=>chosenPeriod(w).month;
 expect(month()).toBe('2026-09');
 api.fetchFinanceSummaryTable.mockResolvedValue(good({...table(),rows:[],total:0}));
 await chooseMonth(w,'2026-11');await w.find('.scope-filters').trigger('submit');await flushPromises();
 expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_month:'2026-11'}),expect.objectContaining({signal:expect.any(AbortSignal)}));
 expect(w.find('.empty').text()).toContain('当前筛选条件下没有记录');
 expect(month()).toBe('2026-11');
 await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();
 expect(w.find('.count').text()).toBe('0 条原始流水（不分摊）');
 await w.find('[data-attribution="pending"]').trigger('click');await flushPromises();
 expect(w.find('.count').text()).toBe('0 条待归属明细');
 expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();w.unmount();
});

it('同条件更新保留旧结果且不可交互，成功后替换',async()=>{
 vi.useFakeTimers();const w=render();await flushPromises();let finish;
 api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));api.fetchFinanceSummary.mockResolvedValue(good({...batch(),revision:1}));
 await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(w.find('.summary-table').text()).toContain('119,410.00');expect(w.text()).toContain('当前展示上次结果');expect(w.find('.pagination').text()).toContain('上次结果');expect(w.find('.pagination').text()).toContain('1 / 3');expect(w.findAll('.pagination button').every(button=>button.attributes('disabled')!==undefined)).toBe(true);expect(w.find('.summary-table').attributes('inert')).toBeDefined();
 const next=table();next.revision=1;next.rows[0].values.sales='123.00';finish(good(next));await flushPromises();expect(w.find('.summary-table').text()).toContain('123.00');expect(w.text()).not.toContain('当前展示上次结果');w.unmount();
});
it('跨租户更新立即清空旧结果，合并状态不重复发起重算',async()=>{
 vi.useFakeTimers();const w=render();await flushPromises();api.fetchFinanceSummary.mockResolvedValue(good({...batch(),refresh_job:{status:'queued',phase:'merging'}}));await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(w.text()).toContain('来源变更正在合并');expect(api.rebuildFinanceSummary).not.toHaveBeenCalled();
 api.fetchFinanceSummary.mockResolvedValue(good({...batch(),tenant_id:'another',dataset:2}));api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(()=>{}));await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(w.text()).not.toContain('119,410.00');w.unmount();
});

it('只读快速完成任务在300毫秒后展示，不重复提交查询',async()=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:71,status:'queued'}}));
 api.fetchFinanceSummaryJob.mockResolvedValue(good({pending:false,job:{id:71,status:'ready'},result:table()}));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(299);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();
 await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(w.text()).toContain('119,410.00');expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);
 await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);w.unmount();
});
it.each([['queued',[300,750,1500,3000,5000,5000]],['running',[300,750,1500,1500,1500]]])('只读%s任务逐步降频并保持频率上限',async(status,delays)=>{
 autoPolling();const data={pending:true,job:{id:72,status}};api.fetchFinanceSummaryTable.mockResolvedValueOnce(good(data));api.fetchFinanceSummaryJob.mockResolvedValue(good(data));
 const w=render();await flushPromises();
 for(const [index,delay]of delays.entries()){
  await vi.advanceTimersByTimeAsync(delay-1);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(index);
  await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(index+1);
 }
 expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
});
it.each([{phase:'merging'},{phase:'retrying'},{error_code:'CALCULATOR_BUSY'}])('明确等待阶段保持5秒低频：%j',async(fields)=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:73,status:'queued',...fields}}));
 api.fetchFinanceSummaryJob.mockResolvedValue(good({pending:false,job:{id:73,status:'ready'},result:table()}));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(4999);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();
 await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);w.unmount();
});
it('重建任务不启用快速只读轮询',async()=>{
 autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));api.rebuildFinanceSummary.mockResolvedValue(good({pending:true,job:{id:74,status:'queued'}}));
 api.fetchFinanceSummaryJob.mockResolvedValue(good({pending:false,job:{id:74,status:'ready'},result:databaseBatch()}));
 const w=render();await flushPromises();await w.findAll('button').find(b=>b.text()==='更新汇总').trigger('click');await flushPromises();
 await vi.advanceTimersByTimeAsync(4999);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();
 await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);expect(api.rebuildFinanceSummary).toHaveBeenCalledTimes(1);w.unmount();
});
it('页面隐藏暂停轮询，恢复立即读取任务结果',async()=>{
 vi.useFakeTimers();let hidden=false;vi.spyOn(document,'hidden','get').mockImplementation(()=>hidden);
 api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:7,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValue(good({pending:false,job:{id:7,status:'ready'},result:table()}));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(100);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();hidden=true;document.dispatchEvent(new Event('visibilitychange'));await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();hidden=false;document.dispatchEvent(new Event('visibilitychange'));await flushPromises();expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);expect(w.text()).toContain('119,410.00');w.unmount();
});

it('轻量轮询复用目录，版本变化后才重取完整元数据和结果',async()=>{
 vi.useFakeTimers();let revision=0;
 api.fetchFinanceSummary.mockImplementation(params=>Promise.resolve(good(params?.status?{lightweight:true,tenant_id:'test-tenant',dataset:1,revision,can_edit:false,source_available:true,refresh_job:null,automatic_update_enabled:true}:{...batch(),revision})));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(30000);await flushPromises();
 expect(api.fetchFinanceSummary).toHaveBeenLastCalledWith({native:1,status:1},expect.objectContaining({signal:expect.any(AbortSignal)}));expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);expect(w.text()).toContain('119,410.00');expect(w.find('.scope-filters').text()).toContain('SP6TH');
 revision=1;await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.fetchFinanceSummary).toHaveBeenLastCalledWith({native:1},expect.objectContaining({signal:expect.any(AbortSignal)}));expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(2);w.unmount();
});
it('打开汇总记录按需读取最新历史，不重算当前表格',async()=>{
 const w=render();await flushPromises();api.fetchFinanceSummary.mockResolvedValue(good({...batch(),rebuild_history:[{id:1,dataset_id:1,result_dataset_id:2,status:'ready',created_at:'2026-11-01T00:00:00Z'}]}));
 await w.findAll('button').find(b=>b.text()==='汇总记录').trigger('click');await flushPromises();expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(2);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);expect(w.text()).toContain('1 → 2');w.unmount();
});

it('权限范围变化立即清空旧结果与店铺目录，不等待新表格完成',async()=>{
 vi.useFakeTimers();api.fetchFinanceSummary.mockResolvedValue(good({...batch(),access_signature:'old'}));const w=render();await flushPromises();
 let finish;api.fetchFinanceSummary.mockResolvedValueOnce(good({lightweight:true,tenant_id:'test-tenant',dataset:1,revision:0,can_edit:false,source_available:true,access_signature:'new'})).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(w.text()).not.toContain('119,410.00');expect(w.find('.scope-filters').exists()).toBe(false);
 finish(good({...batch(),access_signature:'new',can_edit:false,can_view_settings:false}));await flushPromises();expect(w.text()).not.toContain('广告及账务设置');expect(w.text()).toContain('119,410.00');w.unmount();
});

it('自动检查暂停原因和时间展示，轻量轮询恢复健康后移除警告',async()=>{
 vi.useFakeTimers();const health={state:'paused',checked_at:'2026-11-25T01:00:00Z',message:'自动更新执行账号权限不足',recovery:'请管理员恢复权限。'};
 api.fetchFinanceSummary.mockResolvedValueOnce(good({...batch(),automation_health:health}));const w=render();await flushPromises();expect(w.find('.summary-status').text()).toContain(health.message);expect(w.find('.summary-status').text()).toContain('最近检查');expect(w.find('.summary-status').text()).toContain(health.recovery);
 api.fetchFinanceSummary.mockResolvedValue(good({lightweight:true,tenant_id:'test-tenant',dataset:1,revision:0,can_edit:true,source_available:true,automatic_update_enabled:true,automation_health:{...health,state:'healthy',message:'最近检查未发现需要更新的来源'}}));await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(w.find('.summary-status').exists()).toBe(false);expect(w.text()).toContain('119,410.00');w.unmount();
});

it.each([null,502,503])('状态读取临时故障%s退避后恢复且不重复提交',async(http_status)=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:91,status:'queued'}}));
 api.fetchFinanceSummaryJob.mockResolvedValueOnce({success:false,http_status,code:http_status?'HTTP_'+http_status:'HTTP_NETWORK_ERROR',message:'临时连接失败'}).mockResolvedValueOnce(good({pending:false,job:{id:91,status:'ready'},result:table()}));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(300);await flushPromises();expect(w.text()).toContain('自动重试');
 await vi.advanceTimersByTimeAsync(999);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(w.text()).toContain('119,410.00');expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
});
it('状态读取连续故障最多重试三次',async()=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:92,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValue({success:false,http_status:503,message:'服务暂不可用'});
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(7300);await flushPromises();expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(4);expect(w.text()).toContain('服务暂不可用');await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(4);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
});
it('状态读取退避期间卸载不再请求',async()=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:93,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValue({success:false,http_status:502,message:'临时连接失败'});
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(300);w.unmount();await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);
});

it.each([401,403])('状态读取权限错误%s立即停止，不自动重试',async(http_status)=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:94,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValue({success:false,http_status,message:'访问权限已失效'});
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(300);await flushPromises();expect(w.text()).toContain('访问权限已失效');await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);w.unmount();
});
it('抛出的网络中断也只重试状态读取',async()=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:95,status:'queued'}}));api.fetchFinanceSummaryJob.mockRejectedValueOnce(Object.assign(Error('连接中断'),{code:'ERR_NETWORK'})).mockResolvedValueOnce(good({pending:false,job:{id:95,status:'ready'},result:table()}));
 const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(1300);await flushPromises();expect(w.text()).toContain('119,410.00');expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
});

it('过期首个响应的权限错误不清空当前结果',async()=>{
 let finish;api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 const w=render();await flushPromises();await w.find('[data-view="country"]').trigger('click');await new Promise(resolve=>setTimeout(resolve,220));await flushPromises();expect(w.text()).toContain('119,410.00');
 finish({success:false,http_status:403,message:'旧请求权限失效'});await flushPromises();expect(w.text()).toContain('119,410.00');expect(w.text()).not.toContain('旧请求权限失效');w.unmount();
});
it.each(['detail','history'])('隐藏页面关闭%s立即清理等待且不影响表格',async(kind)=>{
 autoPolling();const call=kind==='detail'?api.fetchFinanceSummaryDetail:api.fetchFinanceSummaryHistory;call.mockResolvedValue(good({pending:true,job:{id:96,status:'queued'}}));
 const w=render();await flushPromises();
 if(kind==='detail')await w.find('.summary-table .amount').trigger('click');else{await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();await w.findAll('button').find(b=>b.text()==='操作记录').trigger('click');}
 await flushPromises();const removed=vi.spyOn(document,'removeEventListener');vi.spyOn(document,'hidden','get').mockReturnValue(true);document.dispatchEvent(new Event('visibilitychange'));await flushPromises();
 const drawer=w.findAllComponents({name:'ElDrawer'}).find(c=>c.props('modelValue'));drawer.vm.$emit('update:modelValue',false);await flushPromises();
 expect(removed).toHaveBeenCalledWith('visibilitychange',expect.any(Function));await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();expect(w.find('.table-scroll').exists()).toBe(true);w.unmount();
});
it.each(['detail','history'])('关闭%s后迟到权限响应不清空表格',async(kind)=>{
 let finish;const call=kind==='detail'?api.fetchFinanceSummaryDetail:api.fetchFinanceSummaryHistory;call.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));const w=render();await flushPromises();
 if(kind==='detail')await w.find('.summary-table .amount').trigger('click');else{await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();await w.findAll('button').find(b=>b.text()==='操作记录').trigger('click');}
 await flushPromises();w.findAllComponents({name:'ElDrawer'}).find(c=>c.props('modelValue')).vm.$emit('update:modelValue',false);await flushPromises();finish({success:false,http_status:403,message:'已关闭请求权限失效'});await flushPromises();expect(w.find('.table-scroll tbody tr').text()).toContain('SP6TH');w.unmount();
});

it('自动检测迟到的权限响应不干扰新的视图查询',async()=>{
 autoPolling();const w=render();await flushPromises();let finish;api.fetchFinanceSummary.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await vi.advanceTimersByTimeAsync(30000);await flushPromises();
 await w.find('[data-view="country"]').trigger('click');await flushPromises();finish({success:false,http_status:403,message:'旧检测权限失效'});await flushPromises();expect(w.text()).toContain('119,410.00');expect(w.text()).not.toContain('旧检测权限失效');w.unmount();
});
it('关闭重开汇总记录后旧权限响应不覆盖新结果',async()=>{
 const w=render();await flushPromises();let finish;api.fetchFinanceSummary.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await w.findAll('button').find(b=>b.text()==='汇总记录').trigger('click');await flushPromises();
 w.findAllComponents({name:'ElDialog'}).find(c=>c.props('title')==='汇总记录').vm.$emit('update:modelValue',false);await flushPromises();
 api.fetchFinanceSummary.mockResolvedValueOnce(good({...batch(),rebuild_history:[{id:5,dataset_id:1,result_dataset_id:5,status:'ready'}]}));await w.findAll('button').find(b=>b.text()==='汇总记录').trigger('click');await flushPromises();expect(w.text()).toContain('1 → 5');
 finish({success:false,http_status:403,message:'已关闭记录权限失效'});await flushPromises();expect(w.text()).toContain('1 → 5');expect(w.text()).toContain('119,410.00');w.unmount();
});
it('关闭汇总记录后旧成功响应不切换当前批次',async()=>{
 const w=render();await flushPromises();let finish;api.fetchFinanceSummary.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await w.findAll('button').find(b=>b.text()==='汇总记录').trigger('click');await flushPromises();
 w.findAllComponents({name:'ElDialog'}).find(c=>c.props('title')==='汇总记录').vm.$emit('update:modelValue',false);await flushPromises();finish(good({...batch(),dataset:99,revision:9}));await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);expect(w.text()).toContain('119,410.00');w.unmount();
});

it('切换表格取消旧读取信号，卸载取消当前读取',async()=>{
 autoPolling();let finish;api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));const w=render();await flushPromises();const old=api.fetchFinanceSummaryTable.mock.calls[0][2].signal;expect(old.aborted).toBe(false);
 await w.find('[data-view="country"]').trigger('click');expect(old.aborted).toBe(true);await vi.advanceTimersByTimeAsync(200);await flushPromises();const latest=api.fetchFinanceSummaryTable.mock.calls.at(-1)[2].signal;expect(latest.aborted).toBe(false);
 finish({success:false,code:'REQUEST_CANCELED',message:'请求已取消'});await flushPromises();expect(w.text()).toContain('119,410.00');w.unmount();expect(latest.aborted).toBe(true);
});
it.each(['detail','history'])('关闭%s取消进行中的状态读取且不重试',async(kind)=>{
 autoPolling();const call=kind==='detail'?api.fetchFinanceSummaryDetail:api.fetchFinanceSummaryHistory;call.mockResolvedValue(good({pending:true,job:{id:98,status:'queued'}}));let finish;api.fetchFinanceSummaryJob.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));const w=render();await flushPromises();
 if(kind==='detail')await w.find('.summary-table .amount').trigger('click');else{await w.find('[data-view="detail"]').trigger('click');await flushPromises();await publishedFlow(w);await flushPromises();await w.findAll('button').find(b=>b.text()==='操作记录').trigger('click');}
 await flushPromises();await vi.advanceTimersByTimeAsync(300);await flushPromises();const signal=api.fetchFinanceSummaryJob.mock.calls[0][1].signal;expect(signal.aborted).toBe(false);w.findAllComponents({name:'ElDrawer'}).find(c=>c.props('modelValue')).vm.$emit('update:modelValue',false);await flushPromises();expect(signal.aborted).toBe(true);
 finish({success:false,code:'REQUEST_CANCELED',message:'请求已取消'});await flushPromises();await vi.advanceTimersByTimeAsync(10000);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);expect(w.text()).not.toContain('自动重试');w.unmount();
});

it('恢复标签页保留故障重试的剩余退避时间',async()=>{
 vi.useFakeTimers();let hidden=false;vi.spyOn(document,'hidden','get').mockImplementation(()=>hidden);api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:101,status:'queued'}}));api.fetchFinanceSummaryJob.mockResolvedValueOnce({success:false,http_status:503,message:'临时故障'}).mockResolvedValueOnce(good({pending:false,job:{id:101,status:'ready'},result:table()}));const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(300);
 await vi.advanceTimersByTimeAsync(200);hidden=true;document.dispatchEvent(new Event('visibilitychange'));await vi.advanceTimersByTimeAsync(200);hidden=false;document.dispatchEvent(new Event('visibilitychange'));await flushPromises();expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);await vi.advanceTimersByTimeAsync(599);expect(api.fetchFinanceSummaryJob).toHaveBeenCalledTimes(1);await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(w.text()).toContain('119,410.00');w.unmount();
});
it('表格切换立即移除隐藏页面的旧轮询监听',async()=>{
 autoPolling();api.fetchFinanceSummaryTable.mockResolvedValueOnce(good({pending:true,job:{id:102,status:'queued'}}));const w=render();await flushPromises();vi.spyOn(document,'hidden','get').mockReturnValue(true);document.dispatchEvent(new Event('visibilitychange'));const removed=vi.spyOn(document,'removeEventListener');await w.find('[data-view="country"]').trigger('click');await flushPromises();expect(removed).toHaveBeenCalledWith('visibilitychange',expect.any(Function));w.unmount();
});
it('关闭汇总记录取消元数据HTTP读取',async()=>{
 const w=render();await flushPromises();let finish;api.fetchFinanceSummary.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await w.findAll('button').find(b=>b.text()==='汇总记录').trigger('click');await flushPromises();const signal=api.fetchFinanceSummary.mock.calls.at(-1)[1].signal;expect(signal.aborted).toBe(false);w.findAllComponents({name:'ElDialog'}).find(c=>c.props('title')==='汇总记录').vm.$emit('update:modelValue',false);await flushPromises();expect(signal.aborted).toBe(true);finish({success:false,code:'REQUEST_CANCELED',message:'请求已取消'});await flushPromises();expect(w.text()).toContain('119,410.00');w.unmount();
});

it('费率构成只展示子项及合计费率，金额与含金额来源不进入抽屉',async()=>{
 api.fetchFinanceSummaryDetail.mockResolvedValue(good({title:'订单费用率 · 构成',sales:'119410',amount:'-29626',rate:'-24.81%',note:'分类小计不重复计入',parts:[{label:'平台费用',subtotal:true,level:2,amount:'-29626',rate:'-24.81%',source:'单件金额 123.45'},{label:'佣金',level:3,amount:'-100',rate:'-0.08%'}],records:[{key:'raw',amount:'-100',description:'原始记录'}],html:'金额123.45'}));
 const w=render();await flushPromises();await w.findAll('[aria-label="财务指标展示方式"] button')[1].trigger('click');await w.find('[data-field="order_fee"] button').trigger('click');await flushPromises();const drawer=w.findAllComponents({name:'ElDrawer'}).find(c=>c.props('modelValue'));
 expect(drawer.text()).toContain('-24.81%');expect(drawer.text()).toContain('-0.08%');expect(drawer.text()).toContain('佣金');expect(drawer.text()).not.toContain('29,626.00');expect(drawer.text()).not.toContain('119,410.00');expect(drawer.text()).not.toContain('123.45');expect(drawer.findAll('thead th').map(c=>c.text())).toEqual(['子项','占本行销售额']);expect(drawer.find('iframe').exists()).toBe(false);w.unmount();
});
it('金额构成继续展示金额和来源，不受费率抽屉影响',async()=>{
 const w=render();await flushPromises();await w.find('[data-field="order_fee"] button').trigger('click');await flushPromises();const drawer=w.findAllComponents({name:'ElDrawer'}).find(c=>c.props('modelValue'));expect(drawer.text()).toContain('-29,626.00');expect(drawer.findAll('thead th').map(c=>c.text())).toEqual(['子项','金额','占本行销售额']);w.unmount();
});

it('维度和区间先暂存，用户查询时只计算最终条件一次',async()=>{
 const data=table();data.options.periods_by_month={'2026-09':{week:[{value:'2026-09-14',label:'第三周'},{value:'2026-09-07',label:'第二周'}]}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));const w=render();await flushPromises();const calls=api.fetchFinanceSummaryTable.mock.calls.length;
 await chooseDimension(w,'week');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(calls);await chooseInterval(w,'2026-09-07');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(calls);expect(w.find('.result-context').text()).toContain('月度');
 await w.find('.scope-filters').trigger('submit');await flushPromises();expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(calls+1);expect(api.fetchFinanceSummaryTable).toHaveBeenLastCalledWith(1,expect.objectContaining({filter_period_type:'week',filter_period:'2026-09-07'}),expect.anything());w.unmount();
});
it('计算中仍可调整周期并查询，旧请求取消且不锁住区间',async()=>{
 const data=table();data.options.periods_by_month={'2026-09':{week:[{value:'2026-09-14',label:'第三周'}]}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));const w=render();await flushPromises();let finish;api.fetchFinanceSummaryTable.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await w.find('.scope-filters').trigger('submit');await flushPromises();const oldSignal=api.fetchFinanceSummaryTable.mock.calls.at(-1)[2].signal;
 expect(w.find('.period-trigger').attributes('disabled')).toBeUndefined();await chooseDimension(w,'week');await flushPromises();expect(w.find('.period-trigger').attributes('disabled')).toBeUndefined();expect(w.find('.scope-filters button[type="submit"]').attributes('disabled')).toBeUndefined();await w.find('.scope-filters').trigger('submit');await flushPromises();expect(oldSignal.aborted).toBe(true);finish({success:false,code:'REQUEST_CANCELED'});await flushPromises();expect(w.find('.result-context').text()).toContain('周度');w.unmount();
});

it('未提交的周期筛选暂停自动检测，避免后台查询打断编辑',async()=>{
 autoPolling();api.fetchFinanceSummary.mockResolvedValue(good(databaseBatch()));const w=render();await flushPromises();await chooseDimension(w,'week');await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(1);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);expect(w.text()).toContain('筛选已修改');await w.find('.scope-filters').trigger('submit');await flushPromises();expect(w.text()).not.toContain('筛选已修改');await vi.advanceTimersByTimeAsync(30000);await flushPromises();expect(api.fetchFinanceSummary).toHaveBeenCalledTimes(2);w.unmount();
});

it('旧响应来源列表只渲染50笔并本地翻页，下钻仍使用原始来源键',async()=>{
 const records=Array.from({length:101},(_,i)=>({key:'source:'+i,date:'2026-10-01',description:'合成来源'+i,amount:'1'}));
 api.fetchFinanceSummaryDetail.mockResolvedValue(good({title:'来源',sales:'101',amount:'101',parts:[],records}));
 const w=render();await flushPromises();await w.find('.summary-table tbody button').trigger('click');await flushPromises();
 expect(w.findAll('.source-records tbody tr')).toHaveLength(50);
 await w.findAll('.source-records .pagination button')[1].trigger('click');await flushPromises();
 expect(w.find('.source-records tbody tr').text()).toContain('合成来源50');expect(api.fetchFinanceSummaryDetail).toHaveBeenCalledTimes(1);
 await w.findAll('.source-records .pagination button')[1].trigger('click');await flushPromises();
 expect(w.findAll('.source-records tbody tr')).toHaveLength(1);
 await w.find('.source-records tbody button').trigger('click');await flushPromises();
 expect(api.fetchFinanceSummaryDetail).toHaveBeenLastCalledWith(1,expect.objectContaining({source_key:'source:100'}),expect.anything());w.unmount();
});
it('新响应按服务端来源总数翻页，不重新生成汇总',async()=>{
 const records=Array.from({length:51},(_,i)=>({key:'source:'+i,description:'合成来源'+i,amount:'1'}));
 api.fetchFinanceSummaryDetail.mockImplementation((id,query)=>Promise.resolve(good({title:'来源',sales:'51',amount:'51',parts:[],records:query.flow_page===2?records.slice(50):records.slice(0,50),records_total:51,records_page:query.flow_page||1,records_page_size:50})));
 const w=render();await flushPromises();await w.find('.summary-table tbody button').trigger('click');await flushPromises();
 expect(w.find('.source-records summary').text()).toContain('51');
 await w.findAll('.source-records .pagination button')[1].trigger('click');await flushPromises();
 expect(api.fetchFinanceSummaryDetail).toHaveBeenLastCalledWith(1,expect.objectContaining({flow_page:2}),expect.anything());
 expect(w.findAll('.source-records tbody tr')).toHaveLength(1);expect(api.fetchFinanceSummaryTable).toHaveBeenCalledTimes(1);w.unmount();
});

it('当前页金额与费率读取随汇总返回的构成，不再请求独立任务',async()=>{
 const data=table(),parts={title:'订单销售额 · 构成',amount:'119410',sales:'119410',rate:'100.00%',parts:[{label:'已汇总商品金额',amount:'119410',rate:'100.00%'}],records:[],records_total:200,records_page:1,records_page_size:50};
 data.rows[0].compositions={sales:parts};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));const w=render();await flushPromises();
 await w.find('.summary-table [data-field="sales"] .amount').trigger('click');await flushPromises();expect(w.text()).toContain('已汇总商品金额');expect(api.fetchFinanceSummaryDetail).not.toHaveBeenCalled();expect(api.fetchFinanceSummaryJob).not.toHaveBeenCalled();
 const disclosure=w.find('.source-records');disclosure.element.open=true;await disclosure.trigger('toggle');await flushPromises();expect(api.fetchFinanceSummaryDetail).toHaveBeenCalledTimes(1);expect(api.fetchFinanceSummaryDetail.mock.calls[0][1].include_records).toBe(1);w.unmount();
});
it('费率模式使用同一构成，不显示金额和原始来源，也不新增任务',async()=>{
 const data=table();data.rows[0].compositions={sales:{title:'销售构成',amount:'119410',rate:'100.00%',parts:[{label:'已汇总费率子项',amount:'119410',rate:'100.00%'}],records:[],records_total:200}};api.fetchFinanceSummaryTable.mockResolvedValue(good(data));const w=render();await flushPromises();
 await w.findAll('button').find(b=>b.text()==='费率／利润率').trigger('click');await w.find('.summary-table [data-field="sales"] .amount').trigger('click');await flushPromises();expect(w.text()).toContain('已汇总费率子项');expect(api.fetchFinanceSummaryDetail).not.toHaveBeenCalled();expect(w.find('.source-records').exists()).toBe(false);w.unmount();
});
