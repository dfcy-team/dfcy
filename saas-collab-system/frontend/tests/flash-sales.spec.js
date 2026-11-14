import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { inject, nextTick, provide, reactive, toRef } from 'vue';
import { ElMessageBox } from 'element-plus';
const api = vi.hoisted(() => ({flashRequest:vi.fn()}));
const navigation = vi.hoisted(() => ({route:null}));
vi.mock('../src/api/flashSales', async original => ({...await original(), ...api}));
vi.mock('vue-router', () => ({useRoute:() => navigation.route,useRouter:() => ({replace:vi.fn()})}));
import { copyPayload, copyRows, flashTime } from '../src/api/flashSales';
import FlashCopyDialog from '../src/views/marketing/FlashCopyDialog.vue';
import FlashSalesWorkspace from '../src/views/marketing/FlashSalesWorkspace.vue';
import FlashBatchDialog from '../src/views/marketing/FlashBatchDialog.vue';
import FlashActivityDetail from '../src/views/marketing/FlashActivityDetail.vue';
let wrappers = [];
beforeEach(() => {navigation.route=reactive({query:{}});api.flashRequest.mockReset();localStorage.clear();vi.stubGlobal('ResizeObserver',class {observe(){} unobserve(){} disconnect(){}});});
afterEach(() => {wrappers.forEach(w => w.unmount());wrappers=[];vi.useRealTimers();vi.unstubAllGlobals();});
const tableRows = Symbol('flash-test-rows');
const stubs = {
  ElDrawer:{props:['modelValue'],template:'<section v-if="modelValue"><slot/></section>'},
  ElDialog:{props:['modelValue'],template:'<section v-if="modelValue"><slot/><slot name="footer"/></section>'},
  ElButton:{props:['disabled'],template:'<button :disabled="disabled"><slot/></button>'},
  ElAlert:{props:['title'],template:'<p>{{ title }}</p>'},
  ElSelect:{name:'ElSelect',props:['modelValue'],emits:['update:modelValue'],template:'<select :value="modelValue" @change="$emit(\'update:modelValue\',$event.target.value)"><slot/></select>'},
  ElOption:{props:['value','label'],template:'<option :value="value">{{ label }}</option>'},
  ElInput:{props:['modelValue'],emits:['update:modelValue'],template:'<input :value="modelValue" @input="$emit(\'update:modelValue\',$event.target.value)"/>'},
  ElInputNumber:{props:['modelValue'],emits:['update:modelValue'],template:'<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\',Number($event.target.value))"/>'},
  ElCheckbox:{props:['modelValue','value'],emits:['update:modelValue'],template:'<input type="checkbox" :checked="Array.isArray(modelValue) ? modelValue.includes(value) : modelValue" @change="$emit(\'update:modelValue\',Array.isArray(modelValue) ? ($event.target.checked ? [...modelValue,value] : modelValue.filter(v=>v!==value)) : $event.target.checked)"/>'},
  ElTable:{props:['data'],setup(p){provide(tableRows,toRef(p,'data'));},template:'<div><slot/></div>'},
  ElTableColumn:{props:['label'],setup(){return {rows:inject(tableRows)};},template:'<div><span class="column-label">{{ label }}</span><slot name="header"/><div v-for="(row,i) in rows" :key="i"><slot :row="row"/></div></div>'},
  ElTabs:{template:'<div><slot/></div>'},ElTabPane:{template:'<div><slot/></div>'},ElTag:{template:'<span><slot/></span>'},
  ElForm:{template:'<form><slot/></form>'},ElFormItem:{template:'<label><slot/></label>'},ElPagination:{name:'ElPagination',props:['currentPage','pageSize'],emits:['update:currentPage','current-change'],template:'<div/>'},ElSkeleton:true,
  ElDatePicker:true,ElTimePicker:true,ElRadioGroup:{name:'ElRadioGroup',props:['modelValue'],emits:['update:modelValue'],template:'<div><slot/></div>'},ElRadio:{props:['value'],template:'<label><slot/></label>'},
};
function render(component,props={}) {const w=mount(component,{props,global:{stubs}});wrappers.push(w);return w;}
async function button(w,text) {const b=w.findAll('button').find(node => node.text().includes(text));expect(b).toBeTruthy();await b.trigger('click');await flushPromises();await nextTick();}
async function chooseSlot(w,id) {await button(w,'选择时间段');await w.findComponent({name:'ElRadioGroup'}).vm.$emit('update:modelValue',id);await button(w,'确定时段');}
const product = {item_id:'9223372036854775001',model_id:'9007199254740993',name:'测试商品',price:'12.35',stock:3,purchase_limit:0,status:1};
it('groups product cells after pagination and displays only HTTPS product images', async () => {
  const items=Array.from({length:51},(_,i)=>({...product,model_id:String(i),image:'https://images.example.invalid/product.png'}));
  items.push({...product,item_id:'2',model_id:'0',name:'无效图片',image:'javascript:alert(1)'});
  api.flashRequest.mockResolvedValue({items,details_synced_at:'2030-01-01T00:00:00Z'});
  const w=render(FlashActivityDetail,{activity:{id:7,timezone:'Asia/Manila'}});await flushPromises();
  const table=w.findComponent(stubs.ElTable);const span=table.vm.$attrs['span-method'];
  expect(typeof span).toBe('function');expect(span({row:items[0],rowIndex:0,columnIndex:0})).toEqual([50,1]);expect(span({row:items[1],rowIndex:1,columnIndex:0})).toEqual([0,0]);
  const pagination=w.findComponent({name:'ElPagination'});await pagination.vm.$emit('update:currentPage',2);await nextTick();
  expect(span({row:items[50],rowIndex:0,columnIndex:0})).toEqual([1,1]);
  expect(w.findAll('img')).toHaveLength(1);expect(w.get('img').attributes('src')).toBe('https://images.example.invalid/product.png');
});
it('selects all matching variants of a product across copy pages without changing other products', async () => {
  const items=Array.from({length:51},(_,i)=>({...product,model_id:String(i+1),status:0}));items.push({...product,item_id:'2',model_id:'0',name:'另一个商品',status:0});
  api.flashRequest.mockImplementation(async (path,method,body)=>path.endsWith('/source/') ? {items,slots:[{timeslot_id:999}]} : {id:'p',items:body.items});
  const w=render(FlashCopyDialog,{activity:{id:1,store_id:2,platform_id:'55'}});await flushPromises();
  await w.get(`input[aria-label="整件商品参加 ${product.item_id}"]`).setValue(true);
  await chooseSlot(w,'999');await button(w,'预览');
  const body=api.flashRequest.mock.calls.find(call=>call[0]==='previews/')[2];
  expect(body.items.slice(0,51).every(row=>row.participate)).toBe(true);expect(body.items[51].participate).toBe(false);
});

it('filters target slots by shop-local date and cancels an unconfirmed selection', async () => {
  const slots=[{timeslot_id:1,start_time:Date.parse('2030-01-01T17:00:00Z')/1000,end_time:Date.parse('2030-01-01T18:00:00Z')/1000},{timeslot_id:2,start_time:Date.parse('2030-01-02T17:00:00Z')/1000,end_time:Date.parse('2030-01-02T18:00:00Z')/1000}];
  api.flashRequest.mockImplementation(async (path,method,body)=>path.endsWith('/source/') ? {items:[product],slots} : {id:'p',items:body.items});
  const w=render(FlashCopyDialog,{activity:{id:1,store_id:2,platform_id:'55',timezone:'Asia/Manila'}});await flushPromises();
  await button(w,'选择时间段');await w.get('input[aria-label="筛选时段日期"]').setValue('2030-01-02');
  expect(w.findAllComponents(stubs.ElRadio).map(r=>r.props('value'))).toEqual(['1']);
  await w.findComponent({name:'ElRadioGroup'}).vm.$emit('update:modelValue','1');await button(w,'确定时段');
  await button(w,'选择时间段');await w.findComponent({name:'ElRadioGroup'}).vm.$emit('update:modelValue','2');await button(w,'取消选择');
  await button(w,'预览');expect(api.flashRequest.mock.calls.find(call=>call[0]==='previews/')[2].slot_id).toBe('1');
});
it('filters cached activity details without treating missing values as zero or disabled', async () => {
  api.flashRequest.mockResolvedValue({items:[product,{...product,item_id:'2',model_id:'3',name:'未返回状态商品',status:null,stock:null,available_stock:0}],details_synced_at:'2030-01-01T00:00:00Z'});
  const w=render(FlashActivityDetail,{activity:{id:7,timezone:'Asia/Manila'}});await flushPromises();
  expect(w.text()).toContain('状态未返回');
  await w.get('input[aria-label="搜索商品或规格"]').setValue('未返回状态');
  expect(w.text()).toContain('共 1 条匹配');
  const table=w.findComponent(stubs.ElTable);
  expect(table.props('data')).toHaveLength(1);expect(table.props('data')[0].available_stock).toBe(0);
  expect(table.text()).toContain('—');expect(table.text()).not.toContain('未启用');
  expect(api.flashRequest).toHaveBeenCalledTimes(1);
});

it('applies bulk edits only to participating search results and preserves drafts across pages', async () => {
  const items=Array.from({length:51},(_,i)=>({...product,item_id:String(i+1),model_id:'0',name:i===50?'末页商品':'其他商品'}));
  api.flashRequest.mockImplementation(async (path,method,body) => path.endsWith('/source/') ? {items,slots:[{timeslot_id:999}]} : {id:'p',items:body.items});
  const w=render(FlashCopyDialog,{activity:{id:1,store_id:2,platform_id:'55'}});await flushPromises();
  await w.get('input[aria-label="搜索复制商品"]').setValue('末页');await button(w,'批量编辑');
  await w.get('input[aria-label="批量活动价"]').setValue('9.25');await button(w,'应用');
  expect(w.get('input[aria-label="活动价"]').element.value).toBe('9.25');
  await w.get('input[aria-label="搜索复制商品"]').setValue('');
  expect(w.get('input[aria-label="活动价"]').element.value).toBe('12.35');
  await chooseSlot(w,'999');await button(w,'预览');
  const body=api.flashRequest.mock.calls.find(call=>call[0]==='previews/')[2];
  expect(body.items).toHaveLength(51);expect(body.items[50].price).toBe('9.25');expect(body.items[0].price).toBe('12.35');
});

it('rejects a preview response when edits changed while it was loading', async () => {
  let resolvePreview;
  api.flashRequest.mockImplementation(async path => path.endsWith('/source/') ? {items:[product],slots:[{timeslot_id:999}]} : new Promise(resolve=>{resolvePreview=resolve;}));
  const w=render(FlashCopyDialog,{activity:{id:1,store_id:2,platform_id:'55'}});await flushPromises();
  await chooseSlot(w,'999');await button(w,'预览');
  await w.get('input[aria-label="活动价"]').setValue('10.50');
  resolvePreview({id:'old-preview',items:[product]});await flushPromises();
  expect(w.text()).toContain('配置已变化，请重新生成预览');expect(w.findAll('button').find(b=>b.text()==='确认发布').element.disabled).toBe(true);
});
it('preserves string IDs, manual prices and original disabled participation',() => {const rows=copyRows([product,{...product,model_id:'2',status:0}]);expect(rows[1].participate).toBe(false);rows[0].price='8.19';rows[0].stock=9;expect(copyPayload(rows)[0]).toEqual({item_id:product.item_id,model_id:product.model_id,price:'8.19',stock:9,purchase_limit:0,participate:true});expect(flashTime(null)).toBe('—');});
it('shows a failed preview without clearing edited values and retries publication with the same request ID',async () => {
  const activity={id:1,store_id:2,store_name:'测试店',platform_id:'55',timezone:'Asia/Manila'};
  const bodies=[];let failedPreview=true,failedPublish=true;
  api.flashRequest.mockImplementation(async (path,method,body) => {
    if (path.endsWith('/source/')) return {items:[product],slots:[{timeslot_id:999,start_time:1900000000,end_time:1900003600}]};
    if (path==='previews/') {bodies.push(body);if (failedPreview) {failedPreview=false;throw new Error('预览读取暂未完成');}return {id:'preview-1',items:body.items,expires_at:'2030-01-01T00:00:00Z'};}
    if (path==='batches/') {bodies.push(body);if (failedPublish) {failedPublish=false;throw new Error('响应丢失');}return {id:'batch-1'};}
  });
  const w=render(FlashCopyDialog,{activity});await flushPromises();await nextTick();
  await chooseSlot(w,'999');
  await w.find('input[aria-label="活动价"]').setValue('8.19');
  await button(w,'预览');expect(w.text()).toContain('预览读取暂未完成');expect(w.find('input[aria-label="活动价"]').element.value).toBe('8.19');
  await button(w,'预览');expect(w.text()).toContain('尚未创建活动');
  await button(w,'确认发布');await button(w,'确认发布');
  const submitted=bodies.filter(b=>b.operation==='copy');expect(submitted).toHaveLength(2);expect(submitted[0].request_id).toBe(submitted[1].request_id);expect(w.emitted('submitted')[0]).toEqual(['batch-1']);
});
it('preserves store selection after a workspace refresh',async () => {
  api.flashRequest.mockResolvedValue({workers_enabled:false,capabilities:{execute:true},stores:[{id:1,name:'测试店',code:'SP1',configured:true,stock:7,runs:1,enabled:true,upcoming:[]}],activities:[],batches:[],plans:[],people:[],fallback_ids:[],activity_total:0,batch_total:0});
  const w=render(FlashSalesWorkspace);await flushPromises();await nextTick();
  await w.get('input[aria-label="选择 测试店"]').setValue(true);await button(w,'刷新');
  expect(w.get('input[aria-label="选择 测试店"]').element.checked).toBe(true);expect(w.text()).toContain('运行已选 1');
});
it('shows and filters visible stores even without configuration or activity history',async () => {
  api.flashRequest.mockResolvedValue({workers_enabled:false,capabilities:{},stores:[{id:27,name:'未配置店铺',code:'SP27',configured:false,activity_count:0}],activities:[],batches:[],plans:[],people:[],fallback_ids:[],activity_total:0,batch_total:0});
  const w=render(FlashSalesWorkspace);await flushPromises();
  await button(w,'SP27（0）');
  expect(api.flashRequest.mock.calls.at(-1)[3]).toMatchObject({store_id:27});
  expect(api.flashRequest.mock.calls.every(call => !call[1] || call[1] === 'get')).toBe(true);
});
it('does not display scheduled batches in the compact task bar',async () => {
  api.flashRequest.mockResolvedValue({id:'batch-1',source:'scheduled',operation:'run',created_at:'2030-01-01T00:00:00Z',tasks:[],notifications:[]});
  const w=render(FlashBatchDialog,{batchId:'batch-1'});await flushPromises();await button(w,'收起');expect(w.find('.task-bar').exists()).toBe(false);
});
it.each([true,false])('requires explicit confirmation before resuming a paused original task: %s',async confirmed => {
  const confirm=vi.spyOn(ElMessageBox,'confirm');
  if (confirmed) confirm.mockResolvedValue('confirm'); else confirm.mockRejectedValue('cancel');
  try {
    api.flashRequest.mockResolvedValue({id:'paused-batch',source:'manual',operation:'run',tasks:[{id:8,store_name:'测试店',status:'confirming',retry_paused:true,retry_pause_reason:'连续 3 轮无进展，暂停自动核对',no_progress_count:3,retry_count:15,intents:[]}],notifications:[]});
    const w=render(FlashBatchDialog,{batchId:'paused-batch',canExecute:true});await flushPromises();
    expect(w.text()).toContain('历史重试 15 次');expect(w.text()).toContain('连续无进展 3 轮');
    await button(w,'继续核对原任务');
    const posts=api.flashRequest.mock.calls.filter(call=>call[1]==='post');
    expect(posts).toHaveLength(confirmed ? 1 : 0);
    if (confirmed) expect(posts[0]).toEqual(['batches/paused-batch/','post',{action:'resume',task_id:8,confirmed:true}]);
  } finally {confirm.mockRestore();}
});

it.each([['delete','删除活动','所选活动已确认删除'],['toggle','切换活动状态','活动状态已确认']])('shows the actual %s outcome without creation counts',async (operation,label,message) => {
  api.flashRequest.mockResolvedValue({id:'batch-1',source:'manual',operation,finished_at:'2030-01-01T01:00:00Z',tasks:[{id:1,store_name:'测试店',status:'succeeded',message,requested:1,completed:1,intents:[{id:1,platform_id:'123',target:{},status:'succeeded',result:{message}}]}],notifications:[]});
  const w=render(FlashBatchDialog,{batchId:'batch-1'});await flushPromises();
  expect(w.text()).toContain(label);expect(w.text()).toContain(message);expect(w.text()).toContain('活动 123');
  expect(w.text()).not.toContain('个规格启用');expect(w.text()).not.toContain('个时段');
});

it('separates rejected specifications from unresolved platform results',async () => {
  api.flashRequest.mockResolvedValue({id:'batch-1',source:'manual',operation:'copy',tasks:[{id:1,store_name:'测试店',status:'confirming',requested:1,completed:0,intents:[{id:1,platform_id:'123',target:{},result:{specifications:[{state:'enabled',reason:'已启用'},{state:'rejected',reason:'价格超限'},{state:'unknown',reason:'等待回读'},{state:'mismatch',reason:'库存不一致'}]}}]}],notifications:[]});
  const w=render(FlashBatchDialog,{batchId:'batch-1'});await flushPromises();
  expect(w.text()).toContain('已启用 1 / 被拒绝 1 / 待核对 2');
  expect(w.text()).toContain('1 个规格被拒绝：价格超限');expect(w.text()).toContain('2 个规格待核对，尚不能确认参加结果');
  expect(w.text()).not.toContain('1 个规格被拒绝：等待回读');
});

it('discards an old batch action error after switching to another batch',async () => {
  let rejectAction;
  api.flashRequest.mockImplementation((path,method)=>method==='post' ? new Promise((resolve,reject)=>{rejectAction=reject;}) : Promise.resolve({id:path,source:'manual',operation:'run',tasks:[],notifications:[]}));
  const w=render(FlashBatchDialog,{batchId:'first',canExecute:true});await flushPromises();
  await w.findAll('button').find(b=>b.text()==='重新核对').trigger('click');
  await w.setProps({batchId:'second'});await flushPromises();
  rejectAction(new Error('旧批次失败'));await flushPromises();
  expect(w.text()).not.toContain('旧批次失败');
});

it('restores selections after reopening and reuses an uncertain manual submission ID',async () => {
  const workspace={workspace_key:'tenant:user',workers_enabled:true,capabilities:{execute:true},stores:[{id:1,name:'测试店',configured:true,enabled:true,upcoming:[]}],activities:[],batches:[],plans:[],people:[],fallback_ids:[]};
  const bodies=[];let uncertain=true;
  api.flashRequest.mockImplementation(async (path,method,body) => {
    if(path==='workspace/') return workspace;
    if(path==='batches/') {bodies.push(body);if(uncertain) throw new Error('响应丢失');return {id:'batch-1'};}
    return {id:'batch-1',source:'manual',tasks:[],notifications:[]};
  });
  const first=render(FlashSalesWorkspace);await flushPromises();
  await first.get('input[aria-label="选择 测试店"]').setValue(true);
  await button(first,'运行已选');first.unmount();wrappers=[];
  const reopened=render(FlashSalesWorkspace);await flushPromises();
  expect(reopened.get('input[aria-label="选择 测试店"]').element.checked).toBe(true);
  uncertain=false;await button(reopened,'运行已选');
  expect(bodies).toHaveLength(2);expect(bodies[0].request_id).toBe(bodies[1].request_id);
});

const emptyWorkspace = {workspace_key:'parity:user',workers_enabled:false,capabilities:{execute:true,configure:true,plans:true},stores:[],activities:[],batches:[],plans:[],people:[],fallback_ids:[],activity_total:0,batch_total:0};
it('tracks route changes for tabs and batch details, including clearing the batch',async () => {
  api.flashRequest.mockImplementation(async path=>path==='workspace/' ? emptyWorkspace : {id:path,source:'manual',operation:'run',tasks:[],notifications:[]});
  const w=render(FlashSalesWorkspace);await flushPromises();
  navigation.route.query={activity:'flash',tab:'history',batch:'first'};await flushPromises();
  expect(w.findComponent(stubs.ElTabs).attributes('modelvalue')).toBe('history');
  expect(w.findComponent(FlashBatchDialog).props('batchId')).toBe('first');
  navigation.route.query={activity:'flash',tab:'activities',batch:'second'};await flushPromises();
  expect(w.findComponent(stubs.ElTabs).attributes('modelvalue')).toBe('activities');
  expect(w.findComponent(FlashBatchDialog).props('batchId')).toBe('second');
  navigation.route.query={activity:'flash',tab:'invalid'};await flushPromises();
  expect(w.findComponent(stubs.ElTabs).attributes('modelvalue')).toBe('stores');
  expect(w.findComponent(FlashBatchDialog).exists()).toBe(false);
});

it('ignores an older workspace error after a newer refresh succeeded',async () => {
  let rejectOld;
  api.flashRequest.mockImplementationOnce(()=>new Promise((resolve,reject)=>{rejectOld=reject;})).mockResolvedValue(emptyWorkspace);
  const w=render(FlashSalesWorkspace);await nextTick();await button(w,'刷新');
  rejectOld(new Error('旧筛选请求失败'));await flushPromises();
  expect(w.text()).not.toContain('旧筛选请求失败');expect(w.text()).toContain('0 家店铺');
});

it.each(['success','failure'])('keeps activity details scoped to the latest selection after an old %s',async outcome => {
  let resolveOld,rejectOld;
  api.flashRequest.mockImplementation(path=>path==='activities/1/' ? new Promise((resolve,reject)=>{resolveOld=resolve;rejectOld=reject;}) : Promise.resolve({items:[{...product,name:'新活动商品'}],details_synced_at:'2030-01-01T00:00:00Z'}));
  const w=render(FlashActivityDetail,{activity:{id:1}});await nextTick();
  await w.setProps({activity:{id:2}});await flushPromises();
  expect(api.flashRequest).toHaveBeenCalledWith('activities/2/');expect(w.text()).toContain('新活动商品');
  if(outcome==='success') resolveOld({items:[{...product,name:'旧活动商品'}]});else rejectOld(new Error('旧活动读取失败'));
  await flushPromises();expect(w.text()).toContain('新活动商品');expect(w.text()).not.toContain('旧活动商品');expect(w.text()).not.toContain('旧活动读取失败');
});
it('keeps notification edits as a draft and saves changed stores together with the fallback', async () => {
  const workspace={...emptyWorkspace,capabilities:{configure:true,notifications:true},stores:[{id:1,code:'SP1',name:'店一',configured:true,version:3,notification_mode:'owner',recipient_ids:[]}],people:[{id:8,name:'测试人员'}]};
  const bodies=[];let fail=true;
  api.flashRequest.mockImplementation(async (path,method,body)=>{if(path==='notifications/') {bodies.push(body);if(fail) throw new Error('暂未保存');return {};}return workspace;});
  const w=render(FlashSalesWorkspace);await flushPromises();await button(w,'飞书通知设置');
  const mode=()=>w.findAllComponents({name:'ElSelect'}).find(c=>c.attributes('aria-label')==='SP1 接收方式');
  await mode().vm.$emit('update:modelValue','fallback');await button(w,'取消');await button(w,'飞书通知设置');expect(mode().props('modelValue')).toBe('owner');
  await mode().vm.$emit('update:modelValue','fallback');await w.findAllComponents({name:'ElSelect'}).find(c=>c.attributes('aria-label')==='兜底接收人').vm.$emit('update:modelValue',[8]);
  await button(w,'保存设置');expect(mode().props('modelValue')).toBe('fallback');fail=false;await button(w,'保存设置');
  expect(bodies).toHaveLength(2);expect(bodies[0]).toEqual({user_ids:[8],stores:[{store_id:1,version:3,notification_mode:'fallback',recipient_ids:[]}]});expect(bodies[1]).toEqual(bodies[0]);
});
it.each([false,true])('rechecks cross-page selected activities before submitting; expired=%s', async expired => {
  const rows=[1,2].map(id=>({id,store_id:1,platform_id:String(100+id),starts_at:'2099-01-01T00:00:00Z',ends_at:'2099-01-01T01:00:00Z',status:1}));
  const submitted=[];
  api.flashRequest.mockImplementation(async (path,method,body,params)=>{
    if(path==='workspace/') return {...emptyWorkspace,stores:[{id:1,configured:true,name:'店一'}],activities:[rows[(params?.page || 1)-1]],activity_total:51};
    if(path.startsWith('activities/')) {const row=rows[Number(path.split('/')[1])-1];return expired && row.id===1 ? {...row,starts_at:'2000-01-01T00:00:00Z'} : row;}
    if(path==='batches/') {submitted.push(body);return {id:`batch-${submitted.length}`};}
    return {id:'batch-1',tasks:[],notifications:[]};
  });
  const w=render(FlashSalesWorkspace);await flushPromises();await w.get('input[aria-label="选择活动 101"]').setValue(true);
  const pagination=w.findAllComponents({name:'ElPagination'})[0];await pagination.vm.$emit('update:currentPage',2);await pagination.vm.$emit('current-change',2);await flushPromises();
  await w.get('input[aria-label="选择活动 102"]').setValue(true);await button(w,'批量开启');
  expect(api.flashRequest).toHaveBeenCalledWith('activities/1/');expect(api.flashRequest).toHaveBeenCalledWith('activities/2/');
  expect(submitted.map(row=>row.activity_id)).toEqual(expired ? [] : ['101','102']);
});
it('preserves separate activity dimensions and opens the selected activity detail', async () => {
  const current={id:11,platform_id:'now',starts_at:'2030-01-01T00:00:00Z',ends_at:'2030-01-01T01:00:00Z',timezone:'Asia/Manila',item_count:2};
  const upcoming=Array.from({length:5},(_,i)=>({...current,id:20+i,platform_id:`future-${i}`,starts_at:`2030-01-0${i+2}T00:00:00Z`}));
  api.flashRequest.mockImplementation(async path => path==='workspace/' ? {...emptyWorkspace,stores:[{id:1,code:'SP1',name:'店一',configured:true,current:[current],upcoming}]} : {...current,items:[]});
  const w=render(FlashSalesWorkspace);await flushPromises();
  const labels=w.findAll('.column-label').map(n=>n.text());
  expect(labels).toContain('正在进行的活动');
  for(let i=1;i<=5;i++) expect(labels).toContain(`接下来的活动${i}`);
  expect(w.findAll('.activity-cell')).toHaveLength(6);
  await w.findAll('.activity-cell')[5].trigger('click');await flushPromises();
  expect(api.flashRequest).toHaveBeenCalledWith('activities/24/');
});

it('skips disabled and in-progress stores when running selected stores', async () => {
  const stores=[{id:1,name:'可运行',enabled:true},{id:2,name:'已停用',enabled:false},{id:3,name:'运行中',enabled:true,latest_task:{status:'running'}}].map(s=>({...s,configured:true,upcoming:[]}));
  api.flashRequest.mockImplementation(async path => path==='workspace/' ? {...emptyWorkspace,stores} : {id:'batch',tasks:[],notifications:[]});
  const w=render(FlashSalesWorkspace);await flushPromises();
  await w.get('input[aria-label="全选店铺"]').setValue(true);await button(w,'运行已选');
  const call=api.flashRequest.mock.calls.find(c=>c[0]==='batches/');expect(call[2].store_ids).toEqual([1]);
});

it('clears activity selections on filter changes and keeps original shortcut dates', async () => {
  api.flashRequest.mockResolvedValue({...emptyWorkspace,activities:[{id:8,store_id:1,platform_id:'88'}]});
  const w=render(FlashSalesWorkspace);await flushPromises();
  await w.get('input[aria-label="选择活动 88"]').setValue(true);
  await button(w,'未来3天');
  const params=api.flashRequest.mock.calls.filter(c=>c[0]==='workspace/').at(-1)[3];
  expect((new Date(params.date_to)-new Date(params.date_from))/86400000).toBe(2);
  expect(w.get('input[aria-label="选择活动 88"]').element.checked).toBe(false);
});

it('saves a time point before selecting shops and displays plan dimensions', async () => {
  const bodies=[];api.flashRequest.mockImplementation(async (path,method,body)=>{if(path==='plans/') bodies.push(body);return path==='workspace/' ? emptyWorkspace : {};});
  const w=render(FlashSalesWorkspace);await flushPromises();await button(w,'定时计划');await button(w,'新增执行时间点');await button(w,'保存时间点');
  expect(bodies).toHaveLength(1);expect(bodies[0].store_ids).toEqual([]);
  expect(w.text()).toContain('执行店铺');expect(w.text()).toContain('下次执行');
});
