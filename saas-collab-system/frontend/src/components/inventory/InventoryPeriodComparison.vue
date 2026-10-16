<template>
  <section class="inventory-comparison">
    <h2>库存周期对比</h2><p>比较两个截止日期的仓库快照；数量差额不代表入库或出库。</p>
    <el-form inline @submit.prevent="run">
      <el-form-item label="基准日期"><el-date-picker v-model="from" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="截止日期"><el-date-picker v-model="to" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="国家／站点"><el-input v-model="site" placeholder="如 PH" /></el-form-item>
      <el-form-item label="仓库编号"><el-input v-model="warehouse" placeholder="全部授权仓库" /></el-form-item>
      <el-button type="primary" native-type="submit" :loading="loading">查询对比</el-button>
      <el-button v-if="jobId" @click="cancel">取消任务</el-button>
      <el-button v-if="jobId && !loading && error" @click="resume">检查任务状态</el-button>
    </el-form>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <p v-if="result && (error || loading || dirty)">以下为上次成功批次；条件修改或查询未完成，明细跳转暂不可用。</p>
    <template v-if="result">
      <p>{{ result.date_from }} 对比 {{ result.date_to }} · 批次 {{ result.snapshot_id }} · {{ result.note }}</p>
      <el-radio-group v-model="metric"><el-radio-button v-for="item in metrics" :key="item.key" :value="item.key">{{ item.label }}</el-radio-button></el-radio-group>
      <div class="warehouse-bars" v-for="row in pageRows" :key="`${row.warehouse_id}-${row.site_code}`">
        <strong>{{ row.warehouse_name }} · {{ row.site_code }}</strong>
        <button v-for="period in ['previous', 'current']" :key="period" :disabled="blocked || !row[period]" @click="drill(row, period)">
          <span>{{ period === 'current' ? '截止日' : '基准日' }}</span><i :class="period" :style="{ width: barWidth(row[period]?.[metric]) }" /><b>{{ number(row[period]?.[metric]) }}</b>
        </button>
        <small>变化 {{ number(row.delta[metric]) }} · 截止日实际快照范围：{{ row.current?.snapshot_oldest || '未提供' }} 至 {{ row.current?.snapshot_newest || '未提供' }}</small>
      </div>
      <el-table :data="pageRows" stripe>
        <el-table-column prop="warehouse_name" label="仓库" /><el-table-column prop="site_code" label="站点" />
        <el-table-column label="基准数量"><template #default="{row}">{{ number(row.previous?.[metric]) }}</template></el-table-column>
        <el-table-column label="截止数量"><template #default="{row}">{{ number(row.current?.[metric]) }}</template></el-table-column>
        <el-table-column label="差额"><template #default="{row}">{{ number(row.delta[metric]) }}</template></el-table-column>
        <el-table-column label="穿透明细" min-width="180"><template #default="{row}"><el-button text :disabled="blocked || !row.previous" @click="drill(row,'previous')">基准明细</el-button><el-button text :disabled="blocked || !row.current" @click="drill(row,'current')">截止明细</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="result.rows.length > 20" v-model:current-page="page" :page-size="20" :total="result.rows.length" layout="prev,pager,next" />
      <el-empty v-if="!result.rows.length" description="授权范围与截止日期内暂无库存快照" />
    </template>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref } from 'vue';
import { useRouter } from 'vue-router';
import { startAnalysisJob, pollAnalysisJob, cancelAnalysisJob, isAccessFailure } from '../../views/reports/periodAnalysis';
import { useAuthStore } from '../../stores/auth';
import { pinia } from '../../stores';
import { canAccessPath } from '../../router/menu';
const auth = useAuthStore(pinia), router = useRouter();
const day = offset => new Date(Date.now() - offset * 86400000).toISOString().slice(0,10);
const from = ref(day(31)), to = ref(day(1)), site = ref(''), warehouse = ref(''), metric = ref('provided_available');
const loading = ref(false), error = ref(''), result = ref(null), jobId = ref(null), applied = ref(''), submitted = ref(''), page = ref(1);
const metrics = [{key:'provided_available',label:'可用数量'},{key:'provided_on_hand',label:'在手数量'},{key:'provided_reserved',label:'锁定数量'},{key:'provided_out_count',label:'缺货 SKU 数'},{key:'unmapped_count',label:'未关联 SKU 数'}];
const signature = computed(() => JSON.stringify([from.value,to.value,site.value,warehouse.value]));
const dirty = computed(() => applied.value !== signature.value);
const blocked = computed(() => loading.value || !!error.value || dirty.value || !canAccessPath(auth.currentUser, '/analytics/inventory'));
const pageRows = computed(() => result.value?.rows.slice((page.value-1)*20,page.value*20) || []);
const maximum = computed(() => Math.max(1,...(result.value?.rows || []).flatMap(row=>[row.current?.[metric.value],row.previous?.[metric.value]]).filter(value=>value != null).map(value=>Math.abs(Number(value)))));
const number = value => value == null ? '未提供' : Number(value).toLocaleString('zh-CN');
const barWidth = value => value == null ? '0%' : `${Math.abs(Number(value))/maximum.value*55}%`;
let controller, sequence = 0;
function clearJob(){jobId.value=null;submitted.value='';}
async function execute(start) {
  if(!start&&(!jobId.value||!submitted.value)) return;
  const current = ++sequence;
  const selected = start ? signature.value : submitted.value;
  if(start) clearJob();
  controller?.abort(); controller = new AbortController(); loading.value=true; error.value='';
  try {
    let response = start ? await startAnalysisJob({dataset:'inventory', mode:'period',date_from:from.value,date_to:to.value,filters:{...(site.value ? {site_code:site.value.toUpperCase()}:{}),...(warehouse.value ? {warehouse_id:warehouse.value}:{})}}, controller.signal) : {success:true,data:{id:jobId.value}};
    if(current!==sequence) return;
    if(!response.success) { if(isAccessFailure(response)){result.value=null;clearJob();} throw new Error(response.message || '查询失败'); }
    if(!response.data?.id) throw new Error('服务器没有返回任务编号');
    jobId.value=response.data.id; submitted.value=selected;
    if(response.data.status!=='completed') response=await pollAnalysisJob(jobId.value,{signal:controller.signal});
    if(current!==sequence) return;
    if(!response.success) { if(isAccessFailure(response)){result.value=null;clearJob();} throw new Error(response.message || '任务查询失败'); }
    if(response.data.status!=='completed') { if(['failed','cancelled','expired'].includes(response.data.status)) clearJob(); throw new Error(response.data.error || '任务未完成'); }
    result.value=response.data.result; applied.value=selected; page.value=1; clearJob();
  } catch(cause) { if(current===sequence && cause.name!=='AbortError') { if([401,403].includes(cause.response?.status)){result.value=null;clearJob();} error.value=cause.message; } }
  finally { if(current===sequence) loading.value=false; }
}
function run(){return execute(true);}
function resume(){return execute(false);}
async function cancel(){const id=jobId.value;sequence++;controller?.abort();loading.value=false;error.value='任务已取消';clearJob();if(id) await cancelAnalysisJob(id);}
function drill(row,period){if(!blocked.value) router.push({path:'/analytics/inventory',query:{...row.drill[period],warehouse:row.warehouse_id}});}
onBeforeUnmount(()=>{sequence++;controller?.abort();});
</script>
<style scoped>
.inventory-comparison{padding:20px;background:#fff;border:1px solid #dce3ec;border-radius:12px}.inventory-comparison p,.warehouse-bars small{color:#59697c;line-height:1.7}.warehouse-bars{padding:16px 0;border-bottom:1px solid #edf0f5}.warehouse-bars button{display:flex;align-items:center;gap:12px;border:0;background:transparent;width:100%;padding:8px 0;text-align:left;cursor:pointer}.warehouse-bars button:disabled{cursor:default}.warehouse-bars i{display:inline-block;height:12px;border-radius:3px;background:#315fc6}.warehouse-bars i.previous{background:#a9b8cd}.warehouse-bars span{width:55px;flex-shrink:0}.warehouse-bars small{display:block}.el-table{margin-top:20px}
</style>
