<template>
 <el-dialog v-model="opened" title="付款币种核对" width="min(620px,95vw)" :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @closed="close">
  <div v-loading="loading">
   <el-alert v-if="error" :title="error" type="error" :closable="false"/>
   <template v-if="data">
    <p>原记录：{{recordLabel || entryId}}</p>
    <p>请按原始转账凭证确认币种。只补充币种依据，不换算金额、不修改原付款及凭证，不重新办理付款。</p>
    <el-alert v-if="data.message" :title="data.message" type="info" :closable="false"/>
    <el-form label-position="top" :disabled="busy || !editable" @submit.prevent>
     <el-form-item label="原付款币种"><el-input v-model="currency" maxlength="3" placeholder="三位币种代码，如 CNY、USD、MYR"/></el-form-item>
     <el-form-item label="确认依据或调整原因"><el-input v-model="reason" maxlength="1000" placeholder="请说明依据哪份凭证确认；无法确认时不要填写"/></el-form-item>
     <el-button v-if="editable" type="primary" :loading="busy" @click="save">保存币种确认</el-button>
    </el-form>
    <details v-if="data.history?.length"><summary>查看确认记录</summary><p v-for="(row,i) in data.history" :key="i">{{row.created_at}} · {{row.currency}} · {{row.reason}}</p></details>
   </template>
  </div>
 </el-dialog>
</template>
<script setup>
import {computed,onUnmounted,ref,watch} from 'vue';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import * as api from '../../api/paymentCurrenciesV2';
const props=defineProps({kind:String,id:[String,Number],entryType:String,entryId:[String,Number],recordLabel:String});
const emit=defineEmits(['updated','closed']);
const auth=useAuthStore(),opened=ref(true),loading=ref(false),busy=ref(false),data=ref(null),currency=ref(''),reason=ref(''),error=ref('');
let generation=0,attempt=null;
const editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage')&&data.value?.can_edit);
function unwrap(r){if(!r?.success)throw new Error(r?.message||'币种确认失败');return r.data;}
async function load(){const token=++generation;data.value=null;error.value='';loading.value=true;try{const r=unwrap(await api.fetchCurrency(props.kind,props.id,props.entryType,props.entryId));if(token!==generation)return;data.value=r;currency.value=r.currency||'';reason.value='';}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
async function save(){if(!editable.value||busy.value)return;const token=generation;try{if(!/^[A-Z]{3}$/.test(currency.value))throw new Error('请填写三位大写币种代码');if(!reason.value.trim())throw new Error('请填写确认依据或调整原因');const body={expected_version:data.value.version,currency:currency.value,reason:reason.value.trim()};const signature=JSON.stringify([props.kind,props.id,props.entryType,props.entryId,body]);if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};busy.value=true;error.value='';unwrap(await api.saveCurrency(props.kind,props.id,props.entryType,props.entryId,body,attempt.key));if(token!==generation)return;attempt=null;await load();emit('updated');}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
function close(){generation++;data.value=null;emit('closed');}
watch(()=>[props.kind,props.id,props.entryType,props.entryId],()=>{attempt=null;load();},{immediate:true});
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;data.value=null;opened.value=false;emit('closed');},{flush:'sync'});
onUnmounted(()=>generation++);
defineExpose({data,currency,reason,error,save});
</script>
