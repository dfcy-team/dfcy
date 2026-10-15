<template>
  <section class="freight-plan">
    <el-form-item label="运输渠道（可选）"><el-select :model-value="form.freight_channel_id" clearable filterable remote :remote-method="searchChannels" :disabled="disabled || !form.freight_company_id" :loading="loading" placeholder="搜索渠道、线路，或沿用公司默认价" aria-label="发运运输渠道" @update:model-value="chooseChannel"><el-option v-for="channel in channelOptions" :key="channel.id" :value="channel.id" :disabled="channel.archived || !channel.current_quote" :label="`${channel.name} · ${channel.origin || ''} · ${channel.cargo_type || ''}`"/></el-select></el-form-item>
    <el-pagination v-if="channelTotal>20" small layout="prev, pager, next" :total="channelTotal" :page-size="20" :current-page="channelPage" :disabled="loading || disabled" @current-change="channelPage=$event;loadChannels()"/>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div v-if="selectedQuote" class="quote-summary"><strong>{{quoteChannelName}} · 报价 v{{selectedQuote.sequence}}</strong><p>{{selectedQuote.billing_basis==='container'?`${selectedQuote.container_type} · ${selectedQuote.container_fee} / 柜`:`${selectedQuote.fee_per_cbm} / 方`}} · {{selectedQuote.prices_include_tax?'含税':'未税'}} · 税点 {{selectedQuote.tax_percent}}%</p><small>批次保存时冻结此报价。实际费用仍在“费用与结算”登记。</small><el-button v-if="newQuoteAvailable" link :disabled="disabled" @click="adoptCurrentQuote">采用当前有效报价 v{{selectedChannel.current_quote.sequence}}</el-button></div>
    <div class="grid"><el-form-item label="实际集装箱编号（可选）"><el-input v-model="form.container_number" :disabled="disabled" maxlength="128" aria-label="实际集装箱编号" placeholder="实际柜号，不是柜型"/></el-form-item><el-form-item label="货柜数量"><el-input-number v-model="form.container_count" :min="1" :max="1000" :precision="0" :disabled="disabled" aria-label="发运货柜数量"/></el-form-item></div>
    <el-form-item label="计划目的仓（可选）"><el-select v-model="form.planned_warehouse_id" clearable :disabled="disabled" placeholder="该国家已启用的合作仓" aria-label="计划目的仓"><el-option v-for="warehouse in warehouseOptions" :key="warehouse.id" :value="warehouse.id" :disabled="warehouse.archived" :label="`${warehouse.name}（${warehouse.code || warehouse.country_code}）${warehouse.archived?' · 历史仓库':''}`"/></el-select></el-form-item>
    <el-form-item v-if="snapshot?.planned_warehouse_id && form.planned_warehouse_id!==snapshot.planned_warehouse_id" label="计划目的仓变更原因"><el-input v-model="form.reason" :disabled="disabled" aria-label="计划目的仓变更原因" placeholder="更换或取消计划仓时必填"/></el-form-item>
    <p class="hint">入库单默认带出计划仓；实际改仓需要填写原因。可使用极风及其他合作仓，库存以对应第三方仓回传为准。</p>
  </section>
</template>
<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { fetchFreightChannels } from '../../api/supplyFreightChannelsV2';
const props=defineProps({form:{type:Object,required:true},countryCode:{type:String,default:''},warehouses:{type:Array,default:()=>[]},snapshot:{type:Object,default:null},disabled:Boolean});
const channels=ref([]),loading=ref(false),error=ref(''),channelPage=ref(1),channelTotal=ref(0),channelSearch=ref(''),selectedChannelCache=ref(null);let requestToken=0;
const selectedChannel=computed(()=>channelOptions.value.find(row=>row.id===props.form.freight_channel_id));
const selectedQuote=computed(()=>{if(props.snapshot?.freight_quote_id && props.form.freight_quote_id===props.snapshot.freight_quote_id)return props.snapshot.freight_quote_snapshot?.quote||null;return selectedChannel.value?.current_quote||null;});
const quoteChannelName=computed(()=>props.form.freight_quote_id===props.snapshot?.freight_quote_id?props.snapshot?.freight_quote_snapshot?.name:selectedChannel.value?.name);
const newQuoteAvailable=computed(()=>!!selectedChannel.value?.current_quote&&selectedChannel.value.current_quote.id!==props.form.freight_quote_id);
const channelOptions=computed(()=>{const result=[...channels.value],id=props.form.freight_channel_id;if(id&&!result.some(row=>row.id===id)){if(selectedChannelCache.value?.id===id)result.push(selectedChannelCache.value);else if(props.snapshot?.freight_channel_id===id){const frozen=props.snapshot.freight_quote_snapshot||{};result.push({...frozen,id,archived:true,current_quote:frozen.quote});}}return result;});
const warehouseOptions=computed(()=>{const result=props.warehouses.filter(row=>row.country_code?.toUpperCase()===props.countryCode.toUpperCase());const prior=props.snapshot;if(prior?.planned_warehouse_id&&!result.some(row=>row.id===prior.planned_warehouse_id))result.push({id:prior.planned_warehouse_id,name:prior.planned_warehouse_name||'原计划仓',country_code:props.countryCode,archived:true});return result;});
async function loadChannels(){const token=++requestToken;if(!props.form.freight_company_id||!props.countryCode){channels.value=[];channelTotal.value=0;loading.value=false;return;}loading.value=true;error.value='';try{const response=await fetchFreightChannels({company_id:props.form.freight_company_id,country_code:props.countryCode,active:'true',search:channelSearch.value,limit:20,offset:(channelPage.value-1)*20});if(token!==requestToken)return;if(!response?.success||!Array.isArray(response.data))throw new Error(response?.message||'渠道读取失败');channels.value=response.data;channelTotal.value=Number(response.count||response.data.length);const chosen=channels.value.find(row=>row.id===props.form.freight_channel_id);if(chosen)selectedChannelCache.value=chosen;}catch(e){if(token===requestToken){channels.value=[];channelTotal.value=0;error.value=e.message;}}finally{if(token===requestToken)loading.value=false;}}
function searchChannels(value){channelSearch.value=value;channelPage.value=1;loadChannels();}
function chooseChannel(value){if(props.disabled)return;const chosen=channelOptions.value.find(row=>row.id===value);if(value&&(!chosen||chosen.archived||!chosen.current_quote))return;props.form.freight_channel_id=value||null;props.form.freight_quote_id=chosen?.current_quote?.id||null;selectedChannelCache.value=chosen||null;}
function adoptCurrentQuote(){if(!props.disabled&&selectedChannel.value?.current_quote)props.form.freight_quote_id=selectedChannel.value.current_quote.id;}
watch(()=>props.form.freight_company_id,(value,previous)=>{if(previous&&value!==previous){props.form.freight_channel_id=null;props.form.freight_quote_id=null;selectedChannelCache.value=null;}});
watch(()=>props.countryCode,(value,previous)=>{if(previous&&value!==previous){props.form.freight_channel_id=null;props.form.freight_quote_id=null;props.form.planned_warehouse_id=null;selectedChannelCache.value=null;}});
watch(()=>[props.form.freight_company_id,props.countryCode],()=>{channelPage.value=1;channelSearch.value='';loadChannels();},{immediate:true});
onUnmounted(()=>requestToken++);
defineExpose({channels,loading,selectedQuote,loadChannels,chooseChannel,searchChannels,channelPage,channelTotal});
</script>
<style scoped>
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.freight-plan :deep(.el-select){width:100%}.quote-summary{padding:14px 16px;background:#eff6ff;border:1px solid #dbeafe;border-radius:8px;margin:10px 0 16px}.quote-summary p{margin:6px 0}.hint,small{font-size:12px;color:#64748b;line-height:1.8}@media(max-width:600px){.grid{grid-template-columns:1fr}}
</style>
