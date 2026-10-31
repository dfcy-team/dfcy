<template>
  <section class="settlement-overview">
    <div v-if="!overview" class="filters"><label>目的国家 <el-select v-model="localCountry" clearable placeholder="全部可访问国家" @change="reload(false)"><el-option v-for="c in data?.country_options||[]" :key="c.id" :value="c.id" :label="c.name"/></el-select></label><el-button @click="reload(false)">刷新</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <PaymentRemindersV2 ref="reminders" :country-id="country" @open="row=>emit('open',row)"/>
    <p class="hint">{{data?.amount_basis}} 定金抵扣单独展示，不重复计入已付现金。采购未付与发货单未付属于不同业务阶段，不相加。</p>
    <div class="summary-grid" v-loading="loading">
      <section v-for="(label,key) in labels" :key="key" class="summary-card">
        <header><h3>{{label}}</h3><el-button link type="primary" @click="openGroup(key)">查看全部单据 →</el-button></header>
        <template v-if="data?.groups?.[key]">
          <button class="balance" @click="openGroup(key)"><small>{{key==='deposit'?'可用定金余额':'已知剩余应付'}}</small><strong>{{money(key==='deposit'?data.groups[key].available:data.groups[key].unsettled)}}</strong></button>
          <div class="metrics"><span>{{key==='deposit'?'采购总额':'已知应付'}}<b>{{money(data.groups[key].amount)}}</b></span><span>已付（含期初）<b>{{money(data.groups[key].paid)}}</b></span><span>历史期初<b>{{money(data.groups[key].opening)}}</b></span><span v-if="['supplier','deposit'].includes(key)">定金抵扣<b>{{money(data.groups[key].applied)}}</b></span></div>
          <p class="hint">待核对 {{data.groups[key].unknown_documents||0}} 张 · 超额 {{money(data.groups[key].over_recorded)}}</p>
          <details><summary>未结金额排行 · 前 10</summary><el-table :data="data.groups[key].ranking||[]" border><el-table-column label="供应商 / 货运公司" min-width="160"><template #default="{row}"><el-button v-if="row.party_id||row.id" link type="primary" @click="openGroup(key,row)">{{row.name}}</el-button><span v-else>未选择国内承运商</span></template></el-table-column><el-table-column label="剩余应付"><template #default="{row}">{{money(row.unsettled)}}</template></el-table-column></el-table></details>
        </template><p v-else class="hint">暂无该类汇总</p>
      </section>
    </div>
    <section v-if="opened" class="document-list">
      <h3>{{labels[queue]}} · {{partyName||'全部往来单位'}}单据</h3>
      <div class="filters"><el-select v-model="queue" aria-label="结算类别" @change="changeKind"><el-option v-for="(label,key) in labels" :key="key" :value="key" :label="label"/></el-select><el-select v-model="status" aria-label="结算状态" @change="resetList"><el-option label="全部单据" value="all"/><el-option label="待核对 / 未结清" value="pending"/><el-option label="已结清" value="settled"/></el-select><el-input v-model="search" clearable placeholder="单号 / 供应商 / 货运公司" @keyup.enter="resetList"/><el-button @click="resetList">查询</el-button><el-button v-if="partyId" @click="clearParty">清除单位筛选</el-button></div>
      <div v-if="listSummary" class="metrics query-totals"><span>查询范围 {{listSummary.documents}} 张 · 待核对 {{listSummary.unknown_documents}} 张</span><span v-for="f in columns" :key="f.key">{{f.label}}<b>{{money(listSummary[f.key])}}</b></span><span v-if="queue==='deposit'">可用定金<b>{{money(listSummary.available_prepayment)}}</b></span></div>
      <div class="filters"><el-select v-model="paymentNature" aria-label="实际付款性质" clearable placeholder="全部实际付款性质" @change="resetList"><el-option label="含对公付款" value="corporate"/><el-option label="含对私付款" value="personal"/><el-option label="对公对私混合付款" value="mixed"/><el-option label="未付款或含未分类已付" value="unknown"/></el-select><el-select v-if="['carrier','clearance'].includes(queue)" v-model="itemStatus" aria-label="费用项目付款状态" @change="resetList"><el-option label="按已付款记录筛选" value=""/><el-option label="全部费用项目" value="all"/><el-option label="未付款项目" value="unpaid"/><el-option label="部分付款项目" value="partial"/><el-option label="已结清项目" value="settled"/></el-select><el-input v-model="paymentItem" clearable :placeholder="itemStatus?'费用项目名称':'已付费用项目名称'" @keyup.enter="resetList"/><el-button @click="resetList">筛选付款</el-button></div>
      <p class="hint">付款性质按有效付款时的收款账户统计；混合付款单可同时出现在对公、对私结果中。选择费用项目状态后，按当前费用明细及有效付款筛选，包含从未付款的项目；历史未分项付款不推定归属。筛选后金额仍为整单金额，未分类含历史期初，定金抵扣不计入现金分类。</p>
      <p v-if="listSummary" class="hint">以上合计覆盖当前筛选的全部单据，不仅是本页。</p>
      <div v-if="listSummary" class="metrics"><span>对公已付<b>{{money(listSummary.corporate_paid)}}</b></span><span>对私已付<b>{{money(listSummary.personal_paid)}}</b></span><span>未分类已付（含期初）<b>{{money(listSummary.unknown_paid)}}</b></span></div>
      <el-alert v-if="listError" :title="listError" type="error" :closable="false"/>
      <el-table :data="rows" border v-loading="listLoading" empty-text="当前范围没有单据">
        <el-table-column label="单号" min-width="180"><template #default="{row}"><el-button link type="primary" @click="emit('open',row)">{{row.number}}</el-button></template></el-table-column>
        <el-table-column prop="country_name" label="国家" min-width="110"/><el-table-column label="供应商 / 货运公司" min-width="150"><template #default="{row}"><el-button v-if="row.party_id" link type="primary" @click="openGroup(queue,{party_id:row.party_id,name:row.party_name})">{{row.party_name}}</el-button><span v-else>{{row.party_name}}</span></template></el-table-column>
        <el-table-column v-for="f in columns" :key="f.key" :label="f.label" min-width="125"><template #default="{row}">{{money(row[f.key])}}</template></el-table-column>
        <el-table-column label="实际付款构成" min-width="185"><template #default="{row}"><div>对公 {{money(row.corporate_paid)}}</div><div>对私 {{money(row.personal_paid)}}</div><div>未分类 {{money(row.unknown_paid)}}</div></template></el-table-column>
        <el-table-column v-if="['carrier','clearance'].includes(queue)" label="费用项目 / 约定性质" min-width="210"><template #default="{row}"><div v-for="item in row.fee_items||[]" :key="item.fee_item_id">{{item.name}} · {{item.nature==='corporate'?'对公':'对私'}} · {{money(item.amount)}}</div><span v-if="!row.fee_items?.length">原总额模式</span></template></el-table-column>
        <el-table-column v-if="queue==='deposit'" label="可用定金" min-width="120"><template #default="{row}">{{money(row.available_prepayment)}}</template></el-table-column>
        <el-table-column label="穿透查看" width="145"><template #default="{row}"><el-button link type="primary" @click="emit('open',row)">金额过程 / 凭证</el-button></template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" @current-change="changePage"/>
    </section>
    <p v-else class="hint">点击汇总金额或“查看全部单据”读取明细；点击单位排行可查看该单位跨单据对账。</p>
    <p v-for="note in data?.notices||[]" :key="note" class="hint">{{note}}</p>
  </section>
</template>
<script setup>
import {computed,onUnmounted,ref,watch} from 'vue';
import PaymentRemindersV2 from './PaymentRemindersV2.vue';
import {fetchDashboard,fetchDashboardQueue} from '../../api/supplyDashboardV2';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
const props=defineProps({overview:Object,countryId:[String,Number]});
const emit=defineEmits(['open']);
const reminders=ref(null);
const auth=useAuthStore(),localCountry=ref(''),ownData=ref(null),data=computed(()=>props.overview||ownData.value);
const labels={supplier:'供应商货款',domestic:'国内运费',carrier:'批次货运费',clearance:'入库清关费用',deposit:'采购定金'};
const paymentNature=ref(''),paymentItem=ref(''),itemStatus=ref('');
const columns=[{key:'due_amount',label:'应付 / 采购金额'},{key:'opening_amount',label:'历史期初已付'},{key:'paid_amount',label:'已付（含期初）'},{key:'applied_amount',label:'定金抵扣'},{key:'remaining_amount',label:'剩余应付'}];
const loading=ref(false),error=ref(''),opened=ref(false),queue=ref('supplier'),status=ref('all'),search=ref(''),partyId=ref(null),partyName=ref(''),rows=ref([]),total=ref(0),page=ref(1),listLoading=ref(false),listError=ref(''),listSummary=ref(null);
let generation=0,listGeneration=0;
const country=computed(()=>props.overview?props.countryId:localCountry.value);
const money=value=>value==null?'待核对':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:4});
async function reload(keepList=false){const token=++generation;if(!keepList){listGeneration++;opened.value=false;rows.value=[];}loading.value=true;error.value='';ownData.value=null;try{const r=await fetchDashboard({section:'costs',...(country.value?{country_id:country.value}:{})});if(token!==generation)return;if(!r?.success)throw new Error(r?.message||'结算汇总读取失败');ownData.value=r.data;}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
async function loadList(){const token=++listGeneration;rows.value=[];total.value=0;listSummary.value=null;listLoading.value=true;listError.value='';try{const r=await fetchDashboardQueue({queue:queue.value,status:status.value,...(itemStatus.value?{item_status:itemStatus.value}:{}),search:search.value,...(paymentNature.value?{payment_nature:paymentNature.value}:{}),...(paymentItem.value.trim()?{payment_item:paymentItem.value.trim()}:{}),limit:20,offset:(page.value-1)*20,...(country.value?{country_id:country.value}:{}),...(partyId.value?{party_id:partyId.value}:{})});if(token!==listGeneration)return;if(!r?.success)throw new Error(r?.message||'对账单据读取失败');rows.value=r.data||[];total.value=Number(r.count||0);listSummary.value=r.summary||null;}catch(e){if(token===listGeneration)listError.value=e.message;}finally{if(token===listGeneration)listLoading.value=false;}}
async function refreshAfterUpdate(){await reminders.value?.refresh();if(!props.overview)await reload(true);if(opened.value)await loadList();}
function openGroup(key,party){queue.value=key;partyId.value=party?.party_id||party?.id||null;partyName.value=party?.name||'';status.value='all';search.value='';paymentNature.value='';paymentItem.value='';itemStatus.value='';page.value=1;opened.value=true;return loadList();}
function resetList(){page.value=1;return loadList();}
function changeKind(){paymentNature.value='';paymentItem.value='';itemStatus.value='';partyId.value=null;partyName.value='';return resetList();}
function clearParty(){partyId.value=null;partyName.value='';return resetList();}
function changePage(value){page.value=value;return loadList();}
watch(()=>[props.countryId,props.overview],()=>{listGeneration++;opened.value=false;rows.value=[];if(!props.overview)reload();},{immediate:true});
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;listGeneration++;ownData.value=null;opened.value=false;rows.value=[];localCountry.value='';if(!props.overview&&!auth.authorizationStale)reload();},{flush:'sync'});
onUnmounted(()=>{generation++;listGeneration++;});
defineExpose({refreshAfterUpdate,openGroup,loadList,reload,rows,status,queue,search,partyId,paymentNature,paymentItem,itemStatus,changeKind,resetList});
</script>
<style scoped>
.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.summary-card,.document-list{background:#fff;border:1px solid #dce4ef;border-radius:8px;padding:18px;margin-bottom:16px;min-width:0}header{display:flex;align-items:center;justify-content:space-between;gap:12px}h3{font-size:16px;margin:0 0 12px}.balance{display:block;width:100%;text-align:left;border:0;border-radius:6px;background:#eff5ff;padding:14px;cursor:pointer;color:#1d4ed8}.balance strong{display:block;font-size:26px;margin-top:6px}.metrics{display:flex;flex-wrap:wrap;gap:12px 22px;margin-top:12px;font-size:13px}.metrics b{display:block;margin-top:5px}.hint{color:#64748b;font-size:13px;line-height:1.7}summary{cursor:pointer;font-size:13px;margin:12px 0}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.filters :deep(.el-select){width:190px}.filters :deep(.el-input){width:min(280px,100%)}@media(max-width:850px){.summary-grid{grid-template-columns:1fr}.summary-card,.document-list{padding:12px}}
</style>
