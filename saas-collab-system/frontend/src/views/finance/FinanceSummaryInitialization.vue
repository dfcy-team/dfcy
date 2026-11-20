<template>
  <section class="initialization" aria-label="财务汇总初始化">
    <h2>{{ state.runtime?.ready ? '尚未初始化财务汇总' : '财务计算依赖尚未就绪' }}</h2>
    <p>先明确店铺和账期，从本租户数据库生成候选试算。核对通过后再发布；不会自动登记费用。</p>
    <p v-if="!state.runtime?.ready" role="alert">缺少：{{ (state.runtime?.missing || []).map(key => ({node:'计算运行时',private_storage:'持久化批次存储',calculation_template:'计算模板'})[key] || key).join('、') }}</p>
    <form v-if="state.can_edit" @submit.prevent="calculate">
      <label>店铺<select v-model="scope.stores" multiple required :disabled="busy"><option v-for="store in state.scope_stores" :key="store.id" :value="store.id">{{ store.code }}</option></select></label>
      <label>开始日期<input v-model="scope.from" type="date" required :disabled="busy"></label>
      <label>结束日期<input v-model="scope.to" type="date" required :disabled="busy"></label>
      <button :disabled="busy || !state.runtime?.ready">生成候选试算</button>
    </form>
    <p v-else>请由具有完整财务范围和导入权限的管理员初始化。</p>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <section v-if="candidate" aria-label="候选试算核对">
      <h3>候选试算 #{{ candidate.dataset }}（尚未发布）</h3>
      <p>账期：{{ candidate.source.database_scope.from }} 至 {{ candidate.source.database_scope.to }}</p>
      <ul>
        <li>金额守恒：{{ candidate.source.reconciliation.conservation_passed ? '通过' : '未通过' }}</li>
        <li>归属完整：{{ candidate.source.reconciliation.attribution_complete ? '完整' : '仍有待归属或缺项' }}</li>
        <li>来源覆盖：{{ candidate.source.source_checks?.coverage_complete ? '已获取' : '存在未获取／待核来源；不按零费用处理' }}</li>
      </ul>
      <p v-if="candidate.source.performance">读取 {{ candidate.source.performance.read_seconds }} 秒 · 总耗时 {{ candidate.source.performance.elapsed_seconds }} 秒</p>
      <table><thead><tr><th>原始币种</th><th>原始流水金额合计（不是利润）</th></tr></thead><tbody><tr v-for="(amount,currency) in candidate.source.source_checks?.original_totals_by_currency" :key="currency"><td>{{ currency }}</td><td>{{ amount }}</td></tr></tbody></table>
      <details><summary>查看来源缺项</summary><ul><li v-for="row in missingSources" :key="row.store_id + ':' + row.kind">{{ storeName(row.store_id) }} · {{ kindNames[row.kind] || row.kind }}：{{ row.status === 'missing' ? '未获取' : '待核' }}</li></ul></details>
      <label v-if="state.can_edit"><input v-model="confirmed" type="checkbox">我已核对试算结果和待核来源，确认发布为有效批次</label>
      <button v-if="state.can_edit" :disabled="busy || !confirmed || !candidate.source.reconciliation.conservation_passed" @click="publish">确认发布候选批次</button>
      <p>发布后自动更新仍关闭，先完成范围和来源核对。</p>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { requestApi } from '../../api/request';
const props = defineProps({state:{type:Object,required:true}});
const emit = defineEmits(['published']);
const scope = reactive({from:'',to:'',stores:[]});
const busy=ref(false),error=ref(''),status=ref(''),candidate=ref(null),confirmed=ref(false);
let alive=true;
const kindNames={sales:'订单销售额',refund:'退款',order_fee:'订单费用',advertising:'广告',product_cost:'商品成本',warehouse_order:'仓库处理费',warehouse_other:'仓库其他费用',gcash:'GCash',promotion:'推广',adjustment:'调整'};
const missingSources=computed(()=>(candidate.value?.source?.source_checks?.coverage || []).filter(row=>['missing','pending'].includes(row.status)));
const storeName=id=>props.state.scope_stores.find(store=>store.id===id)?.code || id;
function unwrap(response){if(!response?.success)throw Error(response?.message || '请求未完成');return response.data;}
async function poll(data){
  const started=Date.now();
  while(alive && data?.job){
    if(data.job.status==='ready'){candidate.value=data.result;status.value='候选试算已完成，尚未发布。';return;}
    if(!data.pending)throw Error(data.job.status==='superseded'?'候选版本已变化，请重新试算。':'候选试算未完成；未发布或替换有效结果，请核对来源后重试。');
    if(Date.now()-started>900000)throw Error('等待超过15分钟，请稍后刷新查看任务；未取消后台计算。');
    status.value=data.job.status==='queued'?'候选任务排队中…':'正在读取来源并核对金额…';
    await new Promise(resolve=>setTimeout(resolve,3000));if(!alive)return;
    data=unwrap(await requestApi({method:'get',url:`/api/finance/summary/jobs/${data.job.id}/`,noMockFallback:true}));
  }
}
async function calculate(){
  if(busy.value)return;busy.value=true;error.value='';candidate.value=null;confirmed.value=false;
  try{await poll(unwrap(await requestApi({method:'post',url:'/api/finance/summary/initialize/',data:{scope:{...scope,stores:[...scope.stores]}},noMockFallback:true})));}
  catch(e){error.value=e.message;status.value='';}finally{busy.value=false;}
}
async function publish(){
  if(busy.value||!confirmed.value||!candidate.value)return;busy.value=true;error.value='';
  try{unwrap(await requestApi({method:'post',url:`/api/finance/summary/${candidate.value.dataset}/publish/`,data:{confirm:true},noMockFallback:true}));emit('published');}
  catch(e){error.value=e.message;}finally{busy.value=false;}
}
onMounted(async()=>{if(!props.state.initialization_job)return;busy.value=true;try{await poll(unwrap(await requestApi({method:'get',url:`/api/finance/summary/jobs/${props.state.initialization_job.id}/`,noMockFallback:true})));}catch(e){error.value=e.message;}finally{busy.value=false;}});
onBeforeUnmount(()=>{alive=false;});
</script>

<style scoped>
.initialization{padding:24px;background:#fff;border:1px solid #dfe5ed;border-radius:8px}.initialization form{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:20px 0}.initialization label{display:flex;gap:8px;flex-direction:column}.initialization select,.initialization input[type=date]{padding:8px;border:1px solid #cbd5e1;border-radius:4px}.initialization select{min-width:180px;min-height:100px}.initialization button{padding:9px 16px;border:1px solid #2563eb;border-radius:4px;background:#2563eb;color:white;cursor:pointer}.initialization button:disabled{opacity:.5;cursor:default}.initialization table{border-collapse:collapse;margin:16px 0}.initialization th,.initialization td{padding:8px 16px;border:1px solid #dfe5ed;text-align:left}.initialization details{margin:16px 0}.initialization input[type=checkbox]{align-self:start}.error{color:#b42318}
</style>
