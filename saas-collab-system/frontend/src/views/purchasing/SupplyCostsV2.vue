<template>
  <AppPage title="费用与结算" subtitle="统一维护发货、货运和清货费用，计算商品成本并登记供应商及货运结算。" :capability="error?'degraded':'connected'" class="sc2-ui">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="按单据维护" name="documents">
        <section class="cost-flow-guide" aria-label="费用处理顺序"><strong>先维护来源费用，再按批次计算成本</strong><span>发货单：国内费用与货款</span><span>发运批次：运费与批次成本</span><span>入库单：清货费用与收货差异</span></section>
        <section class="filters">
          <el-select v-model="kind" aria-label="费用单据类型" @change="resetSearch"><el-option label="供应商发货单" value="shipment"/><el-option label="集货发运批次" value="batch"/><el-option label="入库单" value="inbound"/></el-select>
          <el-input v-model="search" placeholder="单号 / 供应商 / 运单号" clearable @keyup.enter="resetSearch"/><el-button @click="resetSearch">搜索</el-button>
        </section>
        <p class="hint">发货单办理国内发货费用及供应商货款结算；发运批次办理货运费用及货运结算；入库单维护清货费用。结算登记保留来源，不执行实际付款。</p>
        <el-alert v-if="error" :title="error" type="error" :closable="false"/>
        <el-table :data="targets" border v-loading="loading"><el-table-column prop="number" label="单号" min-width="175" class-name="document-number"/><el-table-column label="国家" min-width="120"><template #default="{row}"><CountryFlagV2 :code="row.country_code" :label="row.country_name"/></template></el-table-column><el-table-column label="阶段"><template #default="{row}">{{ stageLabel(row.stage) }}</template></el-table-column><el-table-column prop="version" label="版本"/><el-table-column label="操作"><template #default="{row}"><el-button link type="primary" @click="openTarget(row)">费用与结算</el-button></template></el-table-column></el-table>
        <el-pagination layout="total,prev,pager,next" :total="total" :current-page="page" :page-size="20" @current-change="p=>{page=p;loadTargets()}"/>
        <el-drawer :model-value="!!selected" :title="selected?.number||'费用与结算'" size="min(1100px,96vw)" @close="selected=null" class="sc2-ui" @update:model-value="v=>{if(!v)selected=null}"><FeeCostPanelV2 v-if="selected" :kind="selected.kind" :id="selected.id" :version="selected.version" @updated="onUpdated"/></el-drawer>
      </el-tab-pane>
      <el-tab-pane label="按商品查询" name="products"><ProductCostLedgerV2 v-if="activeTab==='products'" /></el-tab-pane>
    </el-tabs>
  </AppPage>
</template>
<script setup>
import '../../styles/supplyTypography.css';
import {onMounted,onUnmounted,ref,watch} from 'vue';
import {useRoute} from 'vue-router';
import CountryFlagV2 from '../../components/supply-chain/CountryFlagV2.vue';
import AppPage from '../../components/AppPage.vue';
import FeeCostPanelV2 from '../../components/supply-chain/FeeCostPanelV2.vue';
import ProductCostLedgerV2 from '../../components/supply-chain/ProductCostLedgerV2.vue';
import * as api from '../../api/supplyCostsV2';
const route=useRoute();
const activeTab=ref('documents');
const kind=ref('shipment'),search=ref(''),targets=ref([]),total=ref(0),page=ref(1),loading=ref(false),error=ref(''),selected=ref(null);
function stageLabel(value){return ({submitted:'已提交',confirmed:'已入库',draft:'待核对',unmarked:'未标记',departed:'开船',arrived_port:'到港',arrived_warehouse:'到仓'})[value]||value;}
function resetSearch(){linkedRequest++;page.value=1;selected.value=null;loadTargets();}
let targetRequest=0,linkedRequest=0;
async function loadTargets(){const current=++targetRequest,requestedKind=kind.value;loading.value=true;error.value='';targets.value=[];total.value=0;try{const r=await api.fetchCostTargets({kind:requestedKind,search:search.value,limit:20,offset:(page.value-1)*20});if(current!==targetRequest||requestedKind!==kind.value)return;if(!r?.success)throw new Error(r?.message||'请求失败');targets.value=Array.isArray(r.data)?r.data.map(row=>({...row,kind:requestedKind})):[];total.value=Number(r.count||0);}catch(e){if(current===targetRequest)error.value=e.message||'费用单据加载失败';}finally{if(current===targetRequest)loading.value=false;}}
function openTarget(row){linkedRequest++;selected.value={...row,kind:row.kind||kind.value};}
function onUpdated(target){if(selected.value&&target&&selected.value.id===target.id&&selected.value.kind===target.kind)selected.value={...selected.value,...target};}
async function openLinked(){const token=++linkedRequest;const query=route?.query||{};if(query.kind==null&&query.id==null)return;if(!['shipment','batch','inbound'].includes(query.kind)||!/^\d+$/.test(String(query.id))||!Number.isSafeInteger(Number(query.id))||Number(query.id)<1){error.value='关联单据链接无效。';return;}selected.value=null;kind.value=query.kind;activeTab.value='documents';page.value=1;loadTargets();try{const result=await api.fetchCostContext(query.kind,Number(query.id));if(token!==linkedRequest)return;if(!result?.success)throw new Error(result?.message||'关联单据不可用');const target=result.data?.target;if(!target||target.kind!==query.kind||Number(target.id)!==Number(query.id))throw new Error('关联单据不匹配。');selected.value={...target};}catch(e){if(token===linkedRequest)error.value=e.message||'关联单据读取失败';}}
watch(()=>[route?.query?.kind,route?.query?.id],openLinked);
onUnmounted(()=>{targetRequest++;linkedRequest++;});
onMounted(()=>{loadTargets();openLinked();});
defineExpose({loadTargets,targets,selected,kind,search,openTarget,openLinked});
</script>
<style scoped>.filters{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.filters :deep(.el-select){width:190px}.filters :deep(.el-input){width:min(320px,100%)}.hint{color:#64748b;font-size:13px;line-height:1.7}@media(max-width:680px){.filters>*{width:100%!important}}</style>

<style scoped>.cost-flow-guide{display:flex;gap:12px 24px;flex-wrap:wrap;align-items:center;padding:16px 0 20px;border-bottom:1px solid #e5eaf0;margin-bottom:18px}.cost-flow-guide strong{font-size:15px;color:#172033}.cost-flow-guide span{font-size:13px;color:#64748b}</style>
