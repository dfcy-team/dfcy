<template>
  <section class="cost-link" aria-label="费用结算关联">
    <div class="cost-link-heading"><strong>费用与结算</strong><router-link :to="targetRoute"><el-button link type="primary">前往费用与结算</el-button></router-link></div>
    <p class="hint">本单展示关联信息，费用、分摊、成本和结算统一在费用与结算页面维护。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-else-if="context" class="summary">
      <span>本单费用：{{ context.fee ? `${context.fee.amount}（${context.fee.state==='confirmed'?'已确认':'估算'}）` : '未维护' }}</span>
      <span v-if="context.settlement_supported">累计已付：{{ context.target?.paid_amount ?? context.settlement?.recorded_amount ?? '未登记' }}</span>
      <span v-if="context.settlement_supported">预付抵扣：{{context.target?.applied_amount ?? '0.0000'}} · 剩余应付：{{ context.target?.remaining_amount ?? context.settlement?.unsettled_amount ?? '尚未确定' }}</span>
      <span>成本：{{ statusLabel(context.latest_cost?.status) }}</span>
    </div>
    <p v-else class="hint">{{ loading ? '正在读取关联信息…' : '请先保存业务单据。' }}</p>
  </section>
</template>
<script setup>
import {computed,onActivated,onUnmounted,ref,watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {fetchCostContext} from '../../api/supplyCostsV2';
const props=defineProps({kind:{type:String,required:true},id:{type:Number,required:true},version:{type:Number,default:0}});
const emit=defineEmits(['updated']);
const auth=useAuthStore(),context=ref(null),error=ref(''),loading=ref(false);
const canView=computed(()=>!auth.authorizationStale && (auth.hasPermission('supply.v2.view')||auth.hasRouteViewPermission?.('supply.v2.view')));
const targetRoute=computed(()=>({path:'/supply-chain/costs',query:{kind:props.kind,id:String(props.id)}}));
const statusLabel=value=>({estimated:'估算',confirmed:'已确认',recalculation_required:'待复算',incomplete:'资料待完善'})[value]||'尚未计算';
let request=0;
async function load(){const token=++request;context.value=null;error.value='';loading.value=false;if(!canView.value||!props.id)return;loading.value=true;try{const result=await fetchCostContext(props.kind,props.id);if(token!==request)return;if(!result?.success)throw new Error(result?.message||'关联信息读取失败');context.value=result.data;if(context.value?.target)emit('updated',context.value.target);}catch(e){if(token===request)error.value=e.message||'关联信息读取失败';}finally{if(token===request)loading.value=false;}}
watch(()=>[props.kind,props.id,props.version,canView.value],load,{immediate:true});
let activated=false;
onActivated(()=>{if(activated)load();activated=true;});
onUnmounted(()=>{request++;});
</script>
<style scoped>.cost-link{margin:16px 0;padding:14px;border:1px solid #dfe5ee;border-radius:6px}.cost-link-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.hint{color:#64748b;font-size:13px;margin:6px 0}.summary{display:flex;gap:12px 24px;flex-wrap:wrap;font-size:13px}</style>
