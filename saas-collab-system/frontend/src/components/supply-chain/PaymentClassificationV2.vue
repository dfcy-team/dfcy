<template>
  <el-dialog v-model="opened" title="历史付款性质核对" width="min(680px,95vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @closed="close">
    <div v-loading="loading">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="data">
        <p class="hint">原记录：{{ recordLabel || `记录 ${entryId}` }}<template v-if="businessDate"> · 业务日期：{{ businessDate }}</template></p>
        <p><strong>{{ entryType==='opening'?'历史累计已付金额':'原付款金额' }}：{{ data.amount }}</strong></p>
        <p class="hint">只补充对公／对私分类，不改变付款金额、业务日期、原收款账户或凭证，不重新申请付款。</p>
        <el-alert v-if="entryType==='opening'" title="此记录是历史累计已付，分类后仍不作为某月的一笔实际付款。" type="warning" :closable="false" />
        <el-alert v-if="data.message" :title="data.message" type="info" :closable="false" />
        <el-form label-position="top" :disabled="busy || !editable" @submit.prevent>
          <el-form-item label="付款性质"><el-select v-model="nature" aria-label="历史付款性质"><el-option value="unclassified" label="待确认"/><el-option value="corporate" label="对公（正报）"/><el-option value="personal" label="对私"/><el-option value="mixed" label="对公与对私都有"/></el-select></el-form-item>
          <template v-if="nature==='mixed'">
            <el-form-item label="对公（正报）金额"><el-input v-model="corporateAmount" inputmode="decimal" placeholder="最多 4 位小数" aria-label="对公金额"/></el-form-item>
            <el-form-item label="对私金额"><el-input v-model="personalAmount" inputmode="decimal" placeholder="最多 4 位小数" aria-label="对私金额"/></el-form-item>
            <p class="hint">两项金额必须合计等于原记录金额，不能按当前剩余应付填写。</p>
          </template>
          <p v-else-if="nature==='corporate'||nature==='personal'">本笔 {{ data.amount }} 全部归为{{ nature==='corporate'?'对公（正报）':'对私' }}。</p>
          <p v-else class="hint">资料不足时保留待确认，不默认归入对私。</p>
          <el-form-item v-if="editable" label="核对依据／修改原因 *"><el-input v-model="reason" type="textarea" :rows="3" maxlength="1000" placeholder="例如已核对原转账凭证或往来单位确认记录"/></el-form-item>
        </el-form>
        <details v-if="data.history?.length" class="history"><summary>查看分类修改记录</summary><div v-for="(item,index) in data.history" :key="index"><p>{{ timeLabel(item.created_at) }} · {{ item.reason }}</p><p class="hint">{{ allocationLabel(item.allocations) }}</p></div></details>
      </template>
    </div>
    <template #footer><el-button :disabled="busy" @click="opened=false">关闭</el-button><el-button v-if="editable" type="primary" :loading="busy" :disabled="loading" @click="save">保存分类</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import {amountUnits} from '../../utils/payeeSettlement';
import * as api from '../../api/paymentClassificationsV2';
type Allocation={nature:string,amount:string};
type History={created_at:string,reason:string,allocations:Allocation[]};
type Context={version:number,amount:string,allocations:Allocation[],nature:string,can_edit:boolean,message?:string,history:History[]};
const props=defineProps<{kind:string,id:number|string,entryType:string,entryId:number|string,recordLabel?:string,businessDate?:string}>();
const emit=defineEmits<{(event:'closed'):void,(event:'updated'):void}>();
const auth=useAuthStore(),opened=ref(true),loading=ref(false),busy=ref(false),error=ref('');
const data=ref<Context|null>(null),nature=ref('unclassified'),corporateAmount=ref(''),personalAmount=ref(''),reason=ref('');
const editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage')&&data.value?.can_edit===true);
const timeLabel=(value:string)=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—';
const allocationLabel=(rows:Allocation[])=>rows?.length?rows.map(row=>`${row.nature==='corporate'?'对公（正报）':'对私'} ${row.amount}`).join('；'):'待确认';
let generation=0,attempt:{signature:string,key:string}|null=null;
function unwrap(result:any):Context{if(!result?.success)throw new Error(result?.message||'付款分类操作失败');return result.data;}
async function load(){const token=++generation;loading.value=true;error.value='';data.value=null;try{const result=unwrap(await api.fetchClassification(props.kind,props.id,props.entryType,props.entryId));if(token!==generation)return;data.value=result;nature.value=result.nature||'unclassified';corporateAmount.value=result.allocations?.find(row=>row.nature==='corporate')?.amount||'';personalAmount.value=result.allocations?.find(row=>row.nature==='personal')?.amount||'';reason.value='';}catch(e:any){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
async function save(){
  if(busy.value||loading.value||!editable.value||!data.value)return;
  const token=generation;
  try{
    if(!reason.value.trim())throw new Error('请填写核对依据或修改原因');
    let allocations:Allocation[]=[];
    if(nature.value==='corporate'||nature.value==='personal')allocations=[{nature:nature.value,amount:data.value.amount}];
    else if(nature.value==='mixed'){
      const corporate=amountUnits(corporateAmount.value),personal=amountUnits(personalAmount.value);
      if(corporate<=0n||personal<=0n)throw new Error('对公和对私金额都必须大于零');
      if(corporate+personal!==amountUnits(data.value.amount))throw new Error('对公与对私金额合计必须等于原记录金额');
      allocations=[{nature:'corporate',amount:corporateAmount.value.trim()},{nature:'personal',amount:personalAmount.value.trim()}];
    }else if(nature.value!=='unclassified')throw new Error('请选择有效的付款性质');
    const body={expected_version:data.value.version,allocations,reason:reason.value.trim()};
    const signature=JSON.stringify([props.kind,props.id,props.entryType,props.entryId,body]);
    if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};
    busy.value=true;error.value='';unwrap(await api.saveClassification(props.kind,props.id,props.entryType,props.entryId,body,attempt.key));
    if(token!==generation)return;attempt=null;await load();emit('updated');
  }catch(e:any){if(token===generation)error.value=e.message;}finally{busy.value=false;}
}
function close(){generation++;data.value=null;emit('closed');}
watch(()=>[props.kind,props.id,props.entryType,props.entryId],()=>{attempt=null;load();},{immediate:true});
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;data.value=null;opened.value=false;emit('closed');},{flush:'sync'});
onUnmounted(()=>generation++);
defineExpose({data,nature,corporateAmount,personalAmount,reason,error,load,save});
</script>
<style scoped>.hint{color:#64748b;font-size:13px;line-height:1.7}.history{border-top:1px solid #dce4ef;margin-top:16px;padding-top:12px}.history summary{cursor:pointer}.history>div{border-bottom:1px solid #eef2f7;padding:6px 0}</style>
