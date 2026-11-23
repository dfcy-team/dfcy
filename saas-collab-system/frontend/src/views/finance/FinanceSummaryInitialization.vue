<template>
  <section class="initialization" aria-label="财务汇总初始化">
    <header><h2>{{ title }}</h2><p>先选择店铺和账期，生成候选试算；核对完整后发布为有效批次。</p><span>{{ candidate ? '尚未发布' : '初始化' }}</span></header>
    <p v-if="!state.runtime?.ready" role="alert">缺少：{{ missingRuntime }}</p>
    <form v-if="state.can_edit" @submit.prevent="calculate">
      <label>店铺 <ElSelect v-model="scope.stores" multiple filterable collapse-tags collapse-tags-tooltip placeholder="请选择店铺" :disabled="busy" aria-label="店铺"><ElOption v-for="store in state.scope_stores" :key="store.id" :value="store.id" :label="store.code" /></ElSelect></label>
      <label>账期 <ElDatePicker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" :disabled="busy" :disabled-date="isFutureDate" aria-label="账期" /></label>
      <ElButton native-type="submit" type="primary" :loading="busy" :disabled="busy || !state.runtime?.ready || !scopeValid">{{ candidate ? '重新生成候选试算' : '生成候选试算' }}</ElButton>
    </form>
    <p v-else>请由具有完整财务范围和导入权限的管理员初始化。</p>
    <p v-if="status" role="status">{{ status }}</p><p v-if="error" role="alert" class="error">{{ error }}</p>
    <section v-if="candidate" aria-label="候选试算核对">
      <h3>候选试算 #{{ candidate.dataset }} · 尚未发布</h3>
      <dl><dt>店铺</dt><dd>{{ (candidate.source.database_scope.stores || []).map(storeName).join('、') || '未提供店铺范围' }}</dd><dt>账期</dt><dd>{{ candidate.source.database_scope.from }} 至 {{ candidate.source.database_scope.to }}</dd><dt>生成时间</dt><dd>{{ finishedAt || '—' }}</dd></dl>
      <ul><li :class="{error: !candidate.source.reconciliation.conservation_passed}">金额守恒：{{ candidate.source.reconciliation.conservation_passed ? '通过' : '未通过' }}</li><li :class="{error: !candidate.source.reconciliation.attribution_complete}">成本及费用归属：{{ candidate.source.reconciliation.attribution_complete ? '完整' : '仍有待归属或缺项' }}</li><li :class="{error: !candidate.source.source_checks?.coverage_complete}">来源覆盖：{{ candidate.source.source_checks?.coverage_complete ? '完整' : '存在未获取或待核来源' }}</li></ul>
      <p v-if="!allChecks">当前仅供核对，不能发布。请补齐来源及成本、费用归属后重新试算。缺失费用不按零费用处理。</p>
      <p v-if="candidate.source.performance">本次试算读取 {{ candidate.source.performance.read_seconds }} 秒 · 总耗时 {{ candidate.source.performance.elapsed_seconds }} 秒（历史耗时）</p>
      <table><thead><tr><th>原始币种</th><th>原始流水金额合计（非收入、非利润）</th></tr></thead><tbody><tr v-for="(amount,currency) in candidate.source.source_checks?.original_totals_by_currency" :key="currency"><td>{{ currency }}</td><td>{{ amount }}</td></tr></tbody></table>
      <p>成本金额需核对成本月份及业务汇率。</p>
      <h3>来源核对 {{ missingSources.length }} 项待处理</h3><button type="button" @click="showSources=!showSources">{{ showSources ? '收起来源缺项' : '查看来源缺项' }}</button>
      <table v-if="showSources"><thead><tr><th>店铺</th><th>来源</th><th>状态</th><th>待核记录数</th><th>原因与处理</th></tr></thead><tbody>
        <tr v-for="row in pageSources" :key="row.store_id + ':' + row.kind"><td>{{ storeName(row.store_id) }}</td><td>{{ kindNames[row.kind] || row.kind }}</td><td>{{ row.status === 'missing' ? '未获取' : '待归属或待核' }}</td><td>{{ row.status === 'missing' ? '未获取，数量未知' : `${row.unknown_rows ?? 0} / ${row.rows ?? 0} 条` }}</td><td>{{ reason(row) }} <a :href="routeFor(row.kind)">前往核对</a></td></tr>
        <tr v-if="!missingSources.length"><td colspan="5">来源覆盖完整；金额和归属仍须分别通过核对。</td></tr></tbody></table>
      <ElPagination v-if="showSources && missingSources.length > 10" v-model:current-page="page" :page-size="10" :total="missingSources.length" layout="prev, pager, next" />
      <label v-if="state.can_edit"><input v-model="confirmed" type="checkbox" :disabled="!allChecks || busy">我已核对试算结果，确认发布为有效批次</label>
      <button v-if="state.can_edit" :disabled="busy || !confirmed || !allChecks" @click="publish">确认发布候选批次</button><p>发布候选批次不会自动登记费用，发布后自动更新仍关闭。</p>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { ElButton, ElDatePicker, ElOption, ElPagination, ElSelect } from 'element-plus';
import { requestApi } from '../../api/request';
const props = defineProps({state:{type:Object,required:true}});const emit=defineEmits(['published']);
const scope=reactive({from:'',to:'',stores:[]});const dateRange=ref([]),busy=ref(false),error=ref(''),status=ref(''),candidate=ref(null),confirmed=ref(false),finishedAt=ref(''),showSources=ref(false),page=ref(1);let alive=true;
const kindNames={sales:'订单销售额',refund:'退款',order_fee:'订单费用',advertising:'广告',product_cost:'商品成本',warehouse_order:'仓库处理费',warehouse_other:'仓库其他费用',gcash:'GCash',promotion:'推广',adjustment:'调整'};
const missingSources=computed(()=>(candidate.value?.source?.source_checks?.coverage||[]).filter(r=>['missing','pending'].includes(r.status))),pageCount=computed(()=>Math.max(1,Math.ceil(missingSources.value.length/10))),pageSources=computed(()=>missingSources.value.slice((page.value-1)*10,page.value*10)),allChecks=computed(()=>!!candidate.value?.source?.reconciliation?.conservation_passed&&!!candidate.value?.source?.reconciliation?.attribution_complete&&!!candidate.value?.source?.source_checks?.coverage_complete),scopeValid=computed(()=>scope.stores.length&&dateRange.value?.length===2&&dateRange.value[0]<=dateRange.value[1]),title=computed(()=>candidate.value?'候选试算待核对':busy.value?'正在生成候选试算':props.state.runtime?.ready?'尚未初始化财务汇总':'财务计算依赖尚未就绪'),missingRuntime=computed(()=>(props.state.runtime?.missing||[]).map(k=>({node:'计算运行时',private_storage:'持久化批次存储',calculation_template:'计算模板'})[k]||k).join('、'));
function unwrap(r){if(!r?.success)throw Error(r?.message||'请求未完成');return r.data;}function storeName(id){return props.state.scope_stores.find(s=>s.id===id)?.code||id;}
function restoreScope(value){if(!value)return;scope.stores=(value.stores||[]).filter(id=>props.state.scope_stores.some(s=>s.id===id));if(value.from&&value.to){scope.from=value.from;scope.to=value.to;dateRange.value=[value.from,value.to];}}
function isFutureDate(date){const end=new Date();end.setHours(23,59,59,999);return new Date(date)>end;}
function reason(row){return row.status==='missing'?'所选账期没有可核对记录，不能视为零费用。':row.kind==='product_cost'?'成本金额待确认，请核对出库依据、成本月份及业务汇率。':'存在未确认金额，请核对来源记录及归属。'}
function routeFor(kind){return ({warehouse_order:'/finance/warehouse-fees',warehouse_other:'/finance/warehouse-fees',gcash:'/finance/gcash-refunds',promotion:'/sales/special-order-registrations',product_cost:'/products/costs'})[kind]||'/finance/imports';}
async function poll(data){const started=Date.now();while(alive&&data?.job){if(data.job.status==='ready'){candidate.value=data.result;restoreScope(data.result?.source?.database_scope);finishedAt.value=data.job.finished_at?new Date(data.job.finished_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+'（北京）':'';page.value=1;confirmed.value=false;status.value='候选试算已完成，尚未发布。';return;}if(!data.pending)throw Error(data.job.status==='superseded'?'候选版本已变化，请重新试算。':'候选试算未完成；未发布或替换有效结果，请核对来源后重试。');if(Date.now()-started>900000)throw Error('等待超过15分钟，请稍后刷新查看任务；未取消后台计算。');status.value=data.job.status==='queued'?'候选任务排队中…':'正在读取来源并核对金额…';await new Promise(r=>setTimeout(r,3000));if(!alive)return;data=unwrap(await requestApi({method:'get',url:`/api/finance/summary/jobs/${data.job.id}/`,noMockFallback:true}));}}
async function calculate(){if(busy.value||!scopeValid.value)return;scope.from=dateRange.value[0];scope.to=dateRange.value[1];busy.value=true;error.value='';confirmed.value=false;try{await poll(unwrap(await requestApi({method:'post',url:'/api/finance/summary/initialize/',data:{scope:{...scope,stores:[...scope.stores]}},noMockFallback:true})));}catch(e){error.value=e.message;status.value='';}finally{busy.value=false;}}
async function publish(){if(busy.value||!confirmed.value||!allChecks.value||!candidate.value)return;busy.value=true;error.value='';try{unwrap(await requestApi({method:'post',url:`/api/finance/summary/${candidate.value.dataset}/publish/`,data:{confirm:true},noMockFallback:true}));emit('published');}catch(e){error.value=e.message;}finally{busy.value=false;}}
onMounted(async()=>{if(!props.state.initialization_job)return;restoreScope(props.state.initialization_job.scope);busy.value=true;try{await poll(unwrap(await requestApi({method:'get',url:`/api/finance/summary/jobs/${props.state.initialization_job.id}/`,noMockFallback:true})));}catch(e){error.value=e.message;}finally{busy.value=false;}});onBeforeUnmount(()=>{alive=false;});
</script>

<style scoped>
.initialization{padding:24px;background:#fff;border:1px solid #dfe5ed;border-radius:8px}.initialization header{display:flex;align-items:center;justify-content:space-between}.initialization form{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:20px 0}.initialization label{display:flex;gap:8px;flex-direction:column}.initialization select,.initialization input[type=date],.initialization input[type=search]{padding:8px;border:1px solid #cbd5e1;border-radius:4px}.initialization select{min-width:180px;min-height:100px}.initialization button{padding:9px 16px;border:1px solid #2563eb;border-radius:4px;background:#2563eb;color:white;cursor:pointer;margin:4px}.initialization button:disabled{opacity:.5;cursor:default}.initialization table{border-collapse:collapse;margin:16px 0}.initialization th,.initialization td{padding:8px 16px;border:1px solid #dfe5ed;text-align:left}.initialization input[type=checkbox]{align-self:start}.error{color:#b42318}dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px}dd{margin:0}
</style>
