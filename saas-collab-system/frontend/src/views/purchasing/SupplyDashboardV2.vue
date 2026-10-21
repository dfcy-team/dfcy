<template>
  <AppPage title="供应链驾驶舱" subtitle="查看国家业务进度、待办与结算，点击进入对应单据处理。" :capability="error?'degraded':'connected'" class="sc2-ui">
    <section class="cockpit-toolbar">
      <div class="country-switch"><label for="cockpit-country">目的国家</label><el-select id="cockpit-country" v-model="countryId" clearable filterable placeholder="全部可访问国家" aria-label="驾驶舱国家" @change="changeCountry"><el-option v-for="country in countryOptions" :key="country.id" :value="country.id" :label="country.name"><CountryFlagV2 :code="country.country_code" :label="country.name"/></el-option></el-select></div>
      <span class="updated">{{ generatedAt ? `更新于 ${formatTime(generatedAt)}` : '按当前账号授权范围统计' }}</span><el-button :loading="loading" @click="refresh">刷新当前视图</el-button>
    </section>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-tabs v-model="section" @tab-change="changeSection">
      <el-tab-pane label="业务进度与待办" name="operations">
        <template v-if="operations">
          <section class="cockpit-tasks" aria-label="供应链待办" v-loading="loading">
            <button v-for="task in taskCards" :key="task.key" type="button" class="task-card" @click="openQueue(task.key,task.label)"><span>{{ task.label }}</span><strong>{{ number(task.value) }}</strong><small>{{ task.unit }} · 查看明细 →</small></button>
          </section>
          <section class="cockpit-panel"><div class="panel-heading"><h3>供应链数量进度</h3><span>各阶段独立查看，累计采购与发货不相加</span></div>
            <div class="stage-grid"><div v-for="stage in stageCards" :key="stage.key"><span>{{ stage.label }}</span><strong>{{ number(operations.totals?.[stage.key]) }}<small> 件</small></strong></div></div>
            <p class="hint">待拆采购 {{ number(operations.totals?.open_demand_quantity) }} 件，包含有效采购草稿预留；采购单 {{ number(operations.totals?.purchase_orders) }} 张，已提交发货 {{ number(operations.totals?.submitted_shipments) }} 张。</p>
          </section>
          <section class="cockpit-panel"><div class="panel-heading"><h3>{{ countryId ? '国家进度' : '国家对比' }}</h3><span>国家信息来自基础档案</span></div>
            <el-table :data="operations.countries" border empty-text="当前授权范围暂无供应链单据"><el-table-column label="国家" min-width="140"><template #default="{row}"><el-button link @click="selectCountry(row.country_id)"><CountryFlagV2 :code="row.country_code" :label="row.country_name"/></el-button></template></el-table-column><el-table-column prop="unshipped_quantity" label="采购未发货" min-width="120"/><el-table-column prop="unallocated_quantity" label="发货未分配" min-width="120"/><el-table-column prop="awaiting_departure_quantity" label="已分配未发运" min-width="130"/><el-table-column prop="in_transit_quantity" label="运输中" min-width="100"/><el-table-column prop="at_port_quantity" label="已到港" min-width="100"/><el-table-column prop="pending_inbounds" label="待核对入库单" min-width="130"/><el-table-column label="提醒" min-width="190"><template #default="{row}"><span :class="row.overdue_batches?'warning-text':''">到仓逾期 {{ row.overdue_batches }} 批</span><br/><small>未填预计到仓日 {{ row.undated_batches }} 批</small></template></el-table-column></el-table>
          </section>
          <section class="cockpit-note"><strong>库存与货值</strong><p>{{ operations.inventory?.notice }}</p><ul><li v-for="note in operations.notices" :key="note">{{ note }}</li></ul></section>
        </template>
      </el-tab-pane>
      <el-tab-pane label="费用与结算" name="costs">
        <template v-if="costs">
          <p class="hint">{{ costs.amount_basis }}</p>
          <div class="settlement-grid" v-loading="loading"><section v-for="kind in ['supplier','carrier']" :key="kind" class="cockpit-panel"><div class="panel-heading"><h3>{{ kind==='supplier'?'供应商货款':'货运商费用' }}</h3><el-button link type="primary" @click="openQueue(kind,kind==='supplier'?'供应商待核对/待结算':'货运商待核对/待结算')">查看待处理</el-button></div><div class="money-primary"><span>已知未结金额</span><strong>{{ amount(costs.groups[kind].unsettled) }}</strong></div><div class="money-pair"><span>已知应结 <b>{{ amount(costs.groups[kind].amount) }}</b></span><span>已登记累计 <b>{{ amount(costs.groups[kind].recorded) }}</b></span></div><p :class="costs.groups[kind].unknown_documents?'warning-text':'hint'">待定价 / 待确认费用 {{ costs.groups[kind].unknown_documents }} 张；超额登记 {{ amount(costs.groups[kind].over_recorded) }}</p><h4>未结金额排行 · 前 10</h4><el-table :data="costs.groups[kind].ranking" border empty-text="暂无可访问的结算来源"><el-table-column prop="name" :label="kind==='supplier'?'供应商':'货运商'" min-width="135"/><el-table-column label="已知未结" min-width="140"><template #default="{row}">{{ amount(row.unsettled) }}</template></el-table-column><el-table-column prop="unknown_documents" label="待核对单据" width="110"/></el-table></section></div>
          <section class="cockpit-note"><ul><li v-for="note in costs.notices" :key="note">{{ note }}</li></ul><p>付款凭证请进入对应单据的“费用与结算”查看或上传。</p></section>
        </template>
      </el-tab-pane>
    </el-tabs>
    <p v-if="loading&&!operations&&!costs" class="hint" role="status">正在读取驾驶舱…</p>
    <el-drawer v-model="queueOpen" :title="queueTitle" size="min(1000px,96vw)" class="sc2-ui"><el-alert v-if="queueError" :title="queueError" type="error" :closable="false"/><el-table :data="queueRows" border v-loading="queueLoading"><el-table-column prop="number" label="单号" min-width="170"/><el-table-column label="国家" min-width="130"><template #default="{row}"><CountryFlagV2 :code="row.country_code" :label="row.country_name"/></template></el-table-column><el-table-column prop="party_name" label="供应商 / 货运商" min-width="170"/><el-table-column v-if="['supplier','carrier'].includes(queueKind)" label="已知未结" min-width="130"><template #default="{row}">{{ row.unsettled==null?'待核对':amount(row.unsettled) }}</template></el-table-column><el-table-column label="操作" width="105"><template #default="{row}"><el-button link type="primary" @click="visit(row.href)">前往处理</el-button></template></el-table-column></el-table><el-pagination layout="total,prev,pager,next" :total="queueTotal" :current-page="queuePage" :page-size="20" @current-change="changeQueuePage"/></el-drawer>
  </AppPage>
</template>
<script setup>
import '../../styles/supplyTypography.css';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import CountryFlagV2 from '../../components/supply-chain/CountryFlagV2.vue';
import { fetchDashboard, fetchDashboardQueue } from '../../api/supplyDashboardV2';
const router=useRouter(),countryId=ref(''),countryOptions=ref([]),section=ref('operations'),operations=ref(null),costs=ref(null),loading=ref(false),error=ref(''),generatedAt=ref('');
const queueOpen=ref(false),queueKind=ref('purchases'),queueTitle=ref(''),queueRows=ref([]),queueTotal=ref(0),queuePage=ref(1),queueLoading=ref(false),queueError=ref('');
let generation=0,queueGeneration=0;
const number=value=>value==null?'—':Number(value).toLocaleString('zh-CN');
const amount=value=>value==null?'待核对':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const formatTime=value=>new Date(value).toLocaleString('zh-CN',{hour12:false});
const taskCards=computed(()=>{const t=operations.value?.totals||{};return [
  {key:'purchases',label:'采购待发货数量',value:t.unshipped_quantity,unit:'件'},
  {key:'collection',label:'待确认到达集货中心',value:t.waiting_collection,unit:'张发货单'},
  {key:'loading',label:'上门装载待分配',value:t.waiting_factory_loading,unit:'张发货单'},
  {key:'inbounds',label:'待入库核对',value:t.pending_inbounds,unit:'张入库单'}];});
const stageCards=[{key:'purchase_quantity',label:'已下单采购累计'},{key:'unshipped_quantity',label:'采购未发货'},{key:'unallocated_quantity',label:'发货未分配'},{key:'awaiting_departure_quantity',label:'已分配未发运'},{key:'in_transit_quantity',label:'运输中'},{key:'at_port_quantity',label:'已到港'},{key:'at_warehouse_quantity',label:'到仓待核对'}];
async function load(){const token=++generation,requested=section.value;loading.value=true;error.value='';try{const response=await fetchDashboard({section:requested,...(countryId.value?{country_id:countryId.value}:{})});if(token!==generation)return;if(!response?.success)throw new Error(response?.message||'驾驶舱读取失败');countryOptions.value=response.data.country_options||[];generatedAt.value=response.data.generated_at;if(requested==='operations')operations.value=response.data;else costs.value=response.data;}catch(e){if(token===generation)error.value=e.message||'驾驶舱读取失败';}finally{if(token===generation)loading.value=false;}}
function changeCountry(){operations.value=null;costs.value=null;queueOpen.value=false;++queueGeneration;return load();}
function selectCountry(id){countryId.value=id;return changeCountry();}
function changeSection(){++generation;loading.value=false;error.value='';if(!(section.value==='operations'?operations.value:costs.value))return load();generatedAt.value=(section.value==='operations'?operations.value:costs.value)?.generated_at;}
function refresh(){return load();}
function openQueue(kind,title){queueKind.value=kind;queueTitle.value=title;queuePage.value=1;queueOpen.value=true;return loadQueue();}
async function loadQueue(){const token=++queueGeneration;queueLoading.value=true;queueError.value='';queueRows.value=[];queueTotal.value=0;try{const response=await fetchDashboardQueue({queue:queueKind.value,limit:20,offset:(queuePage.value-1)*20,...(countryId.value?{country_id:countryId.value}:{})});if(token!==queueGeneration)return;if(!response?.success)throw new Error(response?.message||'待办读取失败');queueRows.value=response.data||[];queueTotal.value=Number(response.count||0);}catch(e){if(token===queueGeneration)queueError.value=e.message||'待办读取失败';}finally{if(token===queueGeneration)queueLoading.value=false;}}
function changeQueuePage(page){queuePage.value=page;return loadQueue();}
function visit(href){if(typeof href==='string'&&href.startsWith('/supply-chain/'))router.push(href);}
onMounted(load);onUnmounted(()=>{generation++;queueGeneration++;});
defineExpose({load,changeCountry,changeSection,openQueue,loadQueue,countryId,section,operations,costs,queueRows,error});
</script>
<style scoped>
.cockpit-toolbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:8px 0 20px}.country-switch{display:flex;gap:10px;align-items:center}.country-switch .el-select{width:230px}.updated{margin-left:auto;color:#64748b;font-size:12px}.cockpit-tasks{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:12px 0 20px}.task-card{text-align:left;cursor:pointer;background:#fff;border:1px solid #dce4ef;border-radius:10px;padding:20px;color:#23344e;font:inherit}.task-card:hover{border-color:#2563eb;background:#f7faff}.task-card:focus-visible{outline:2px solid #2563eb;outline-offset:3px}.task-card strong{display:block;font-size:29px;font-weight:650;line-height:1.7;color:#1d4ed8}.task-card small{color:#64748b;font-size:12px}.cockpit-panel{background:#fff;border:1px solid #e1e7ef;border-radius:10px;padding:20px;margin-bottom:20px;min-width:0}.panel-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}.panel-heading h3{font-size:16px;margin:0;color:#172033}.panel-heading>span,.hint{font-size:12px;color:#64748b;line-height:1.8}.stage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.stage-grid>div{padding:12px;background:#f5f8fc;border-radius:6px}.stage-grid span{color:#52627a;font-size:13px}.stage-grid strong{display:block;font-size:22px;line-height:1.7;color:#172033;font-weight:600}.stage-grid small{font-size:12px;font-weight:400}.warning-text{color:#b45309;font-size:13px;line-height:1.8}.cockpit-note{font-size:12px;color:#64748b;line-height:1.9;margin-bottom:20px}.cockpit-note ul{padding-left:20px}.settlement-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.money-primary{background:#f0f5ff;border-radius:8px;padding:16px}.money-primary span{font-size:13px;color:#52627a}.money-primary strong{display:block;font-size:28px;color:#1d4ed8;line-height:1.8}.money-pair{display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:#64748b;margin-top:14px}.money-pair b{display:block;color:#23344e;font-size:17px;line-height:1.8}h4{font-size:13px;color:#52627a;margin:22px 0 12px}@media(max-width:1100px){.cockpit-tasks,.stage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.settlement-grid{grid-template-columns:minmax(0,1fr)}}@media(max-width:600px){.cockpit-toolbar{gap:10px}.updated{margin-left:0;width:100%}.cockpit-tasks{gap:10px}.task-card{padding:12px}.task-card strong{font-size:24px}.cockpit-panel{padding:14px}.stage-grid{gap:10px}.country-switch{width:100%}.country-switch .el-select{flex:1;min-width:0}}
</style>
