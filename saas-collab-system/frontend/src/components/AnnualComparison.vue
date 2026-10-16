<template>
  <section class="annual-comparison">
    <h2>国家、平台与店铺周期对比</h2><p>同币种分别比较；每次展示 10 个分组，完整保留全年 12 个月或 52／53 周。</p>
    <el-form inline @submit.prevent="run">
      <el-form-item label="年份"><el-input-number v-model="year" :min="2025" :max="new Date().getFullYear()" /></el-form-item>
      <el-form-item label="分组"><el-select v-model="groupBy"><el-option label="国家" value="country"/><el-option label="平台" value="platform"/><el-option label="店铺" value="store_id"/></el-select></el-form-item>
      <el-form-item label="周期"><el-select v-model="mode"><el-option label="月度" value="monthly"/><el-option label="ISO 周度" value="weekly"/></el-select></el-form-item>
      <el-form-item label="币种筛选"><el-input v-model="filterCurrency" placeholder="如 PHP" /></el-form-item>
      <el-button type="primary" native-type="submit" :loading="loading">查询对比</el-button>
      <el-button v-if="jobId" @click="cancel">取消</el-button>
      <el-button v-if="jobId && error && !loading" @click="execute(false)">检查任务</el-button>
    </el-form>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <p v-if="result && blocked">显示上次成功批次；当前条件未完成查询，明细跳转停用。</p>
    <template v-if="result">
      <p>{{ result.note }} · 批次 {{ result.snapshot_id }}</p>
      <div class="controls"><el-select v-model="currency" aria-label="显示币种"><el-option v-for="value in currencies" :key="value" :label="value" :value="value" /></el-select><el-select v-model="metric" aria-label="指标"><el-option v-for="item in metricOptions" :key="item.key" :value="item.key" :label="item.label"/></el-select></div>
      <div class="matrix-scroll"><table><thead><tr><th>分组 · {{ currency }}</th><th v-for="point in headings" :key="point.label">{{ point.label }}</th></tr></thead><tbody>
        <tr v-for="group in visibleGroups" :key="group.value"><th>{{ group.label }}</th><td v-for="point in group.points" :key="point.label" :style="shade(point.current?.metrics?.[metric])"><button :disabled="blocked || !point.current || !point.drill.current" :title="`${point.start} 至 ${point.end}；${point.partial?'进行中；':''}已采集 ${display(point.current?.metrics?.[metric])}`" @click="inspect(group,point)">{{ display(point.current?.metrics?.[metric]) }}</button></td></tr>
      </tbody></table></div>
      <el-pagination v-if="groups.length > 10" v-model:current-page="page" :page-size="10" :total="groups.length" layout="total,prev,pager,next"/>
      <el-empty v-if="!groups.length" description="当前范围暂无可比较数据"/>
      <el-dialog v-model="open" title="周期比较与明细" width="min(650px,95vw)"><template v-if="selected">
        <p>{{ selected.group.label }} · {{ selected.point.start }} 至 {{ selected.point.end }} · {{ currency }}</p>
        <div v-for="kind in ['current','yoy','previous']" :key="kind" class="period-row"><span>{{ {current:'本期',yoy:'去年同期',previous:'上期'}[kind] }}</span><strong>{{ display(selected.point[kind]?.metrics?.[metric]) }}</strong><el-button :disabled="blocked || !selected.point[kind] || !selected.point.drill[kind] || !canDrill" @click="drill(kind)">查看明细</el-button></div>
        <p>无值表示无已采集记录或来源指标不完整；明细将按原周期条件读取实时数据。</p>
      </template></el-dialog>
    </template>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { pinia } from '../stores';
import { canAccessPath } from '../router/menu';
import { startAnalysisJob, pollAnalysisJob, cancelAnalysisJob, isAccessFailure } from '../views/reports/periodAnalysis';
const props=defineProps({dataset:{type:String,default:'sales'}}),router=useRouter(),auth=useAuthStore(pinia);
const year=ref(new Date().getFullYear()),mode=ref('monthly'),groupBy=ref('country'),filterCurrency=ref(''),currency=ref(''),metric=ref(props.dataset==='advertising'?'expense':'gross_sales');
const loading=ref(false),error=ref(''),result=ref(null),jobId=ref(null),applied=ref(''),submitted=ref(''),page=ref(1),open=ref(false),selected=ref(null);
const metricOptions=computed(()=>props.dataset==='advertising'?[{key:'expense',label:'广告消耗'},{key:'direct_gmv',label:'直接归因 GMV'},{key:'broad_gmv',label:'广泛归因 GMV'}]:[{key:'gross_sales',label:'非取消订单销售额'},{key:'valid_order_count',label:'非取消订单量'}]);
const signature=computed(()=>JSON.stringify([year.value,mode.value,groupBy.value,filterCurrency.value]));
const blocked=computed(()=>loading.value||!!error.value||signature.value!==applied.value);
const currencies=computed(()=>[...new Set((result.value?.groups||[]).map(g=>g.currency).filter(Boolean))]);
const groups=computed(()=>(result.value?.groups||[]).filter(g=>g.currency===currency.value));
const visibleGroups=computed(()=>groups.value.slice((page.value-1)*10,page.value*10));
const headings=computed(()=>groups.value[0]?.points||[]);
const maximum=computed(()=>Math.max(1,...groups.value.flatMap(g=>g.points.map(p=>Math.abs(Number(p.current?.metrics?.[metric.value]||0))))));
const path=computed(()=>props.dataset==='advertising'?'/analytics/advertising-overview':'/sales-management/orders');
const canDrill=computed(()=>canAccessPath(auth.currentUser,path.value));
const display=value=>value==null?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});
const shade=value=>value==null?{}:{background:`rgba(49,95,198,${0.04+Math.abs(Number(value))/maximum.value*0.22})`};
watch(currency,()=>{page.value=1;open.value=false;});
let controller,seq=0;
function clearJob(){jobId.value=null;submitted.value='';}
async function execute(start){
  if(!start&&(!jobId.value||!submitted.value))return;
  const current=++seq,selected=start?signature.value:submitted.value;
  controller?.abort();controller=new AbortController();loading.value=true;error.value='';open.value=false;
  if(start)clearJob();
  try{
    let response=start?await startAnalysisJob({dataset:props.dataset,year:year.value,mode:mode.value,group_by:groupBy.value,filters:filterCurrency.value?{currency:filterCurrency.value.toUpperCase()}:{}},controller.signal):{success:true,data:{id:jobId.value}};
    if(current!==seq)return;
    if(!response.success){if(isAccessFailure(response)){result.value=null;clearJob();}throw new Error(response.message||'请求失败');}
    if(!response.data?.id)throw new Error('服务器没有返回任务编号');
    jobId.value=response.data.id;submitted.value=selected;
    if(response.data.status!=='completed')response=await pollAnalysisJob(jobId.value,{signal:controller.signal});
    if(current!==seq)return;
    if(!response.success){if(isAccessFailure(response)){result.value=null;clearJob();}throw new Error(response.message||'查询失败');}
    if(response.data.status!=='completed'){
      if(['failed','cancelled','expired'].includes(response.data.status))clearJob();
      throw new Error(response.data.error||'任务未完成');
    }
    result.value=response.data.result;applied.value=selected;currency.value=currencies.value[0]||'';page.value=1;clearJob();
  }catch(cause){if(current===seq&&cause.name!=='AbortError'){if([401,403].includes(cause.response?.status)){result.value=null;clearJob();}error.value=cause.message;}}
  finally{if(current===seq)loading.value=false;}
}
function run(){return execute(true);}
async function cancel(){const id=jobId.value;seq++;controller?.abort();loading.value=false;error.value='已取消任务';clearJob();if(id)await cancelAnalysisJob(id);}
function inspect(group,point){if(!blocked.value){selected.value={group,point};open.value=true;}}
function drill(kind){if(blocked.value||!canDrill.value)return;const filters=selected.value.point.drill[kind];router.push({path:path.value,query:props.dataset==='advertising'?{...filters,view:'details',kind:'shop_daily',period_start:filters.date_from,period_end:filters.date_to}:{...filters,exclude_cancelled:'true'}});}
onBeforeUnmount(()=>{seq++;controller?.abort();});
</script>
<style scoped>
.annual-comparison{padding:20px;background:#fff;border:1px solid #dce3ec;border-radius:12px}.annual-comparison p{color:#637286;font-size:13px;line-height:1.7}.controls{display:flex;gap:12px;margin:16px 0}.el-select{min-width:150px}.matrix-scroll{overflow:auto;max-height:620px}table{border-collapse:collapse;min-width:100%;font-size:12px}th,td{border:1px solid #e2e8f0;min-width:90px;text-align:right;padding:8px}th{background:#f5f7fb;position:sticky;top:0}tr th:first-child{left:0;text-align:left;z-index:1;min-width:160px}td button{background:transparent;border:0;color:#233247;cursor:pointer;width:100%;text-align:right;font:inherit}td button:disabled{cursor:default;color:#738198}.period-row{display:flex;align-items:center;justify-content:space-between;padding:12px 0}.el-pagination{margin-top:15px}
</style>
