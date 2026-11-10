<template>
  <section class="payable-split">
    <el-button link type="primary" :disabled="busy" @click="toggle">{{ opened ? '收起' : '查看 / 维护' }}{{ title }}应付性质</el-button>
    <div v-if="opened" v-loading="loading">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template v-if="data">
        <p>往来单位：{{data.party_name || '待确认'}} · 本单应付总额：{{data.payable_amount ?? '待确认'}} {{data.currency || ''}}</p>
        <p>在这里确认整张单据中对公、对私各应付多少，不需要选择收款账户。已付款也包含在应付总额内；付款时间请在付款安排中维护。</p>
        <el-alert v-if="data.stale" title="单据金额或往来单位已变化，原拆分需要重新核对确认。" type="warning" :closable="false" />
        <el-alert v-if="data.read_only_reason" :title="data.read_only_reason" type="info" :closable="false" />
        <el-form label-position="top" :disabled="busy || !editable || disabled" @submit.prevent>
          <div class="split-fields">
            <el-form-item label="单据币种（首次确认后锁定）"><el-input v-model="currency" :disabled="!!data.currency" maxlength="3" placeholder="如 CNY" /></el-form-item>
            <el-form-item label="对公（正报）应付金额"><el-input v-model="corporate" inputmode="decimal" placeholder="可填 0，最多4位小数" /></el-form-item>
            <el-form-item label="对私应付金额"><el-input v-model="personal" inputmode="decimal" placeholder="可填 0，最多4位小数" /></el-form-item>
          </div>
          <p>尚未确定性质的应付金额：{{unclassified}} {{currency}}</p>
          <el-form-item label="本次确认或调整原因"><el-input v-model="reason" maxlength="1000" placeholder="说明确认依据；不确定的金额请保留待核对" /></el-form-item>
          <el-button v-if="editable" type="primary" :loading="busy" @click="save">保存应付性质</el-button>
        </el-form>
        <p>保存不会登记付款、修改合同或改变商品成本，也不会自动修改付款安排。</p>
      </template>
    </div>
  </section>
</template>
<script setup>
import {computed,onUnmounted,ref,watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import {amountUnits} from '../../utils/payeeSettlement';
import * as api from '../../api/payableClassificationV2';
const props=defineProps({kind:String,id:[String,Number],disabled:Boolean});
const emit=defineEmits(['updated']);
const auth=useAuthStore();
const opened=ref(false),loading=ref(false),busy=ref(false),data=ref(null),error=ref('');
const corporate=ref('0'),personal=ref('0'),currency=ref(''),reason=ref('');
let generation=0,attempt=null;
const title=computed(()=>({shipment:'货款',domestic_freight:'国内运费',batch:'批次货运费'}[props.kind]||''));
const editable=computed(()=>!auth.authorizationStale && auth.hasPermission('supply.v2.manage') && data.value?.can_manage===true);
const unclassified=computed(()=>{try{if(data.value?.payable_amount==null)return '待确认';const n=amountUnits(data.value.payable_amount)-amountUnits(corporate.value)-amountUnits(personal.value);if(n<0n)return '拆分金额超过应付总额';return `${n/10000n}.${String(n%10000n).padStart(4,'0')}`;}catch{return '请检查金额';}});
function unwrap(result){if(!result?.success)throw new Error(result?.message||'应付性质操作失败');return result.data;}
async function load(){const token=++generation;loading.value=true;error.value='';data.value=null;try{const result=unwrap(await api.fetchPayableClassification(props.kind,props.id));if(token!==generation)return;data.value=result;corporate.value=String(result.corporate_amount??'0');personal.value=String(result.personal_amount??'0');currency.value=result.currency||'';reason.value='';}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
function toggle(){opened.value=!opened.value;if(opened.value)return load();generation++;loading.value=false;}
async function save(){if(!editable.value||busy.value||props.disabled)return;const token=generation;try{
 if(!reason.value.trim())throw new Error('请填写本次确认或调整原因');
 if(!/^[A-Z]{3}$/.test(currency.value))throw new Error('请确认三位大写币种代码');
 if(data.value.payable_amount==null)throw new Error('请先确认单据应付金额');
 if(amountUnits(corporate.value)+amountUnits(personal.value)>amountUnits(data.value.payable_amount))throw new Error('拆分金额不能超过本单应付总额');
 const body={expected_version:data.value.version,expected_source_version:data.value.source_version,expected_payable_amount:data.value.payable_amount,currency:currency.value,corporate_amount:corporate.value.trim(),personal_amount:personal.value.trim(),reason:reason.value.trim()};
 const signature=JSON.stringify([props.kind,props.id,body]);if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};
 busy.value=true;error.value='';unwrap(await api.savePayableClassification(props.kind,props.id,body,attempt.key));if(token!==generation)return;attempt=null;await load();emit('updated');
 }catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
function reset(){generation++;opened.value=false;data.value=null;corporate.value='0';personal.value='0';currency.value='';reason.value='';error.value='';attempt=null;loading.value=false;}
watch(()=>[props.kind,props.id,cockpitActorKey(auth.currentUser),auth.authorizationStale],reset,{flush:'sync'});
onUnmounted(()=>generation++);
defineExpose({toggle,save,data,corporate,personal,currency,reason,error,unclassified});
</script>
<style scoped>
.payable-split{margin:14px 0;padding:14px;border:1px solid #dce4ef;border-radius:6px}.payable-split p{font-size:13px;line-height:1.7;color:#475569}.split-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}
</style>
