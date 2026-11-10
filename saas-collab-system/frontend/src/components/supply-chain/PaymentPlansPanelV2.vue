<template>
  <section class="plan-panel" :aria-label="title">
    <el-button link type="primary" :disabled="busy" @click="toggle">{{ opened ? '收起' : '查看 / 维护' }}{{ title }}</el-button>
    <div v-if="opened" v-loading="loading">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="data">
        <p>往来单位：{{ data.party_name || '待确认' }} · 剩余应付：{{ data.remaining_amount ?? '待核对' }} {{ data.currency || '' }}</p>
        <el-alert v-if="data.party_changed" :title="`往来单位已变化，原安排属于${data.saved_party_name || '原单位'}。请核对当前单位、金额和到期日，填写原因后重新保存确认。`" type="warning" :closable="false" />
        <p class="hint">先安排对公／对私金额和到期日，提交付款申请时再选择收款账户。保存安排不会增加已付或改变商品成本。</p>
        <el-alert v-if="data.remaining_amount == null" title="应付金额尚未确定，请先在费用与结算中核对金额。" type="warning" :closable="false" />
        <p class="totals">正报（对公）：{{ totals.corporate }} · 对私：{{ totals.personal }} · 计划合计：{{ totals.total }} {{ data.currency || '' }}</p>
        <el-alert v-if="overRemaining" title="单据余额已变化，当前安排扣除已付后超过剩余应付，请核对付款或费用调整。" type="warning" :closable="false" />
        <el-form label-position="top" :disabled="busy || disabled || !editable" @submit.prevent>
          <el-form-item v-if="!data.currency" label="本单费用币种（首次请按原单确认） *"><el-select v-model="currency" filterable allow-create default-first-option placeholder="选择或填写三位币种代码"><el-option v-for="code in currencies" :key="code" :value="code" :label="code"/></el-select><p class="hint">本单应付和安排金额必须使用同一币种；这里不进行汇率换算。保存后币种锁定。</p></el-form-item>
          <div v-for="(line,index) in lines" :key="line.key" class="plan-line">
            <strong class="line-heading">第 {{ index + 1 }} 笔付款安排</strong>
            <p v-if="line.line_id" class="line-balance">已付 {{ line.paid_amount||'0' }} · 占用 {{ line.reserved_amount||'0' }} · 剩余 {{ line.remaining_amount??line.amount }} · 可用 {{ line.available_amount??line.amount }}</p>
            <el-form-item v-if="data.fee_items?.length" label="费用项目 *"><el-select v-model="line.fee_item_id" placeholder="选择本笔所属费用项目" @change="applyItemNature(line)"><el-option v-for="item in data.fee_items" :key="item.fee_item_id" :value="item.fee_item_id" :label="`${item.name} · ${item.nature==='corporate'?'对公（正报）':item.nature==='personal'?'对私':'性质待确认'} · 未付 ${item.remaining_amount}`"/></el-select></el-form-item>
            <el-form-item label="付款性质 *"><el-select v-model="line.nature" aria-label="付款性质"><el-option value="corporate" label="对公（正报）"/><el-option value="personal" label="对私"/></el-select></el-form-item>
            <el-form-item label="计划付款金额 *"><el-input v-model="line.amount" inputmode="decimal" placeholder="最多 4 位小数" aria-label="计划付款金额"/></el-form-item>
            <el-form-item label="币种"><el-input :model-value="currency || '待确认'" disabled/></el-form-item>
            <el-form-item label="计划到期日（待定可留空）"><el-date-picker v-model="line.due_date" type="date" value-format="YYYY-MM-DD" placeholder="待确认" aria-label="计划到期日"/></el-form-item>
            <el-form-item label="说明"><el-input v-model="line.note" maxlength="500" placeholder="如尾款、分期约定"/></el-form-item>
            <el-button v-if="editable" type="danger" link :disabled="busy || disabled || line.has_references" @click="lines.splice(index,1)">移除此笔安排</el-button>
            <small v-if="line.has_references">此安排已有付款申请引用，不能删除或更改身份、金额</small>
          </div>
          <p v-if="!lines.length" class="hint">尚未安排付款；历史已付款不会自动变成待付款计划。</p>
          <template v-if="editable">
            <el-button :disabled="busy || disabled || lines.length >= 100" @click="addLine">添加付款安排</el-button>
            <el-form-item label="本次调整原因 *" class="reason"><el-input v-model="reason" maxlength="1000" type="textarea" placeholder="填写约定或调整原因"/></el-form-item>
            <el-button type="primary" :loading="busy" :disabled="disabled || data.remaining_amount == null" @click="save">保存付款安排</el-button>
          </template>
        </el-form>
        <p class="hint">缺少性质的历史付款保留“待确认”，不会自动归入对私。付款安排尚不自动关联付款审批或核销；实际付款仍从现有付款申请入口办理，付款后请核对并调整剩余安排。</p>
      </template>
    </div>
  </section>
</template>
<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import {amountUnits} from '../../utils/payeeSettlement';
import * as api from '../../api/paymentPlansV2';
type PlanLine={key:number,line_id?:string|number|null,has_references?:boolean,paid_amount?:string,reserved_amount?:string,remaining_amount?:string,available_amount?:string,nature:string,amount:string,currency:string,due_date:string|null,note:string,fee_item_id?:number|null};
type Context={version:number,source_version:number,remaining_amount:string|null,currency:string|null,party_name?:string,party_changed?:boolean,saved_party_name?:string,default_due_date?:string|null,can_manage?:boolean,lines:Partial<PlanLine>[],enriched_lines?:Partial<PlanLine>[],fee_items?:{fee_item_id:number,name:string,remaining_amount:string,nature?:string}[]};
const props=defineProps<{kind:string,id:string|number,disabled?:boolean}>();
const emit=defineEmits<{(event:'updated'):void}>();
const auth=useAuthStore();
const title=computed(()=>({shipment:'货款付款安排',domestic_freight:'国内运费付款安排',batch:'批次货运费付款安排'}[props.kind] || '付款安排'));
const opened=ref(false),loading=ref(false),busy=ref(false),error=ref(''),reason=ref('');
const currency=ref(''),currencies=['CNY','USD','MYR','PHP','IDR','THB','VND','SGD','RUB'];
const data=ref<Context|null>(null),lines=ref<PlanLine[]>([]);
const editable=computed(()=>!auth.authorizationStale && auth.hasPermission('supply.v2.manage') && data.value?.can_manage !== false);
let generation=0,lineKey=0,attempt:{signature:string,key:string}|null=null;
const format=(n:bigint)=>`${n/10000n}.${String(n%10000n).padStart(4,'0')}`;
const totals=computed(()=>{let corporate=0n,personal=0n;try{for(const line of lines.value){const amount=amountUnits(line.amount);if(line.nature==='corporate')corporate+=amount;else if(line.nature==='personal')personal+=amount;}return {corporate:format(corporate),personal:format(personal),total:format(corporate+personal)};}catch{return {corporate:'待填写',personal:'待填写',total:'待填写'};}});
const overRemaining=computed(()=>{try{return data.value?.remaining_amount!=null && lines.value.reduce((n,line)=>n+amountUnits(line.amount)-amountUnits(line.paid_amount||'0'),0n)>amountUnits(data.value.remaining_amount);}catch{return false;}});
function unwrap(result:any):Context{if(!result?.success)throw new Error(result?.message||'付款安排操作失败');return result.data;}
function addLine(){if(!editable.value||busy.value||props.disabled||lines.value.length>=100)return;lines.value.push({key:++lineKey,nature:'',amount:'',currency:data.value?.currency||'',due_date:data.value?.default_due_date||null,note:''});}
function applyItemNature(line:PlanLine){const item=data.value?.fee_items?.find(item=>item.fee_item_id===line.fee_item_id);if(item?.nature==='corporate'||item?.nature==='personal')line.nature=item.nature;}
async function load(){const token=++generation;loading.value=true;error.value='';data.value=null;lines.value=[];try{const result=unwrap(await api.fetchPaymentPlans(props.kind,props.id));if(token!==generation)return;data.value=result;currency.value=result.currency||'';lines.value=(result.enriched_lines||result.lines||[]).map(line=>({key:++lineKey,line_id:line.line_id??null,has_references:!!line.has_references,paid_amount:line.paid_amount,reserved_amount:line.reserved_amount,remaining_amount:line.remaining_amount,available_amount:line.available_amount,nature:line.nature||'',amount:String(line.amount??''),currency:result.currency||'',due_date:line.due_date||null,note:line.note||'',fee_item_id:line.fee_item_id||null}));reason.value='';}catch(e:any){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
function toggle(){opened.value=!opened.value;if(opened.value)return load();generation++;loading.value=false;}
async function save(){
  if(!editable.value||busy.value||props.disabled||!data.value)return;
  const token=generation,kind=props.kind,id=props.id;
  try{
    if(!reason.value.trim())throw new Error('请填写本次调整原因');
    if(data.value.remaining_amount==null)throw new Error('请先核对本单应付金额');
    if(!/^[A-Z]{3}$/.test(currency.value))throw new Error('请按原单确认三位大写币种代码');
    let sum=0n;
    const payload=lines.value.map((line,index)=>{if(!['corporate','personal'].includes(line.nature))throw new Error(`第${index+1}笔请选择对公或对私`);if(data.value!.fee_items?.length&&!line.fee_item_id)throw new Error(`第${index+1}笔请选择费用项目`);const amount=amountUnits(line.amount);if(amount<=0n)throw new Error(`第${index+1}笔金额须大于零`);const original=data.value!.enriched_lines?.find((x:any)=>x.line_id===line.line_id)||data.value!.lines?.find((x:any)=>x.line_id===line.line_id);if(line.has_references&&(line.nature!==original?.nature||String(line.fee_item_id||'')!==String(original?.fee_item_id||'')||amount<(amountUnits(line.paid_amount||'0')+amountUnits(line.reserved_amount||'0'))))throw new Error('已关联申请的安排不能更改付款性质或费用项目，金额不得低于已付与审批占用合计');sum+=amount;return {...(line.line_id?{line_id:line.line_id}:{}),nature:line.nature,amount:line.amount.trim(),currency:currency.value,due_date:line.due_date||null,note:line.note.trim(),...(line.fee_item_id?{fee_item_id:line.fee_item_id}:{})};});
    const cap=lines.value.reduce((n,line)=>n+amountUnits(line.amount)-amountUnits(line.paid_amount||'0'),0n);if(cap>amountUnits(data.value.remaining_amount))throw new Error('付款安排合计扣除已付后不能超过剩余应付');
    const body={expected_version:data.value.version,expected_source_version:data.value.source_version,currency:currency.value,lines:payload,reason:reason.value.trim()};
    const signature=JSON.stringify([kind,id,body]);if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};
    busy.value=true;error.value='';unwrap(await api.savePaymentPlans(kind,id,body,attempt.key));
    if(token!==generation)return;attempt=null;await load();emit('updated');
  }catch(e:any){if(token===generation)error.value=e.message;}finally{busy.value=false;}
}
function reset(){generation++;opened.value=false;data.value=null;lines.value=[];currency.value='';reason.value='';error.value='';attempt=null;loading.value=false;}
watch(()=>[props.kind,props.id,cockpitActorKey(auth.currentUser),auth.authorizationStale],reset,{flush:'sync'});
onUnmounted(()=>generation++);
defineExpose({toggle,load,save,addLine,lines,reason,currency,data,error,totals});
</script>
<style scoped>
.plan-panel{margin:14px 0;padding:14px;border:1px solid #dce4ef;border-radius:6px}.hint{font-size:13px;color:#64748b;line-height:1.7}.totals{font-weight:600}.plan-line{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;padding:14px;margin:12px 0;background:#f7f9fc;border-radius:6px}.line-heading{grid-column:1/-1}.reason{margin-top:14px}.plan-line :deep(.el-date-editor){max-width:100%}
</style>
