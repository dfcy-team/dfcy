<template>
  <section class="terms-panel">
    <el-button link type="primary" :disabled="busy" @click="toggle">{{opened?'收起':'查看 / 维护'}}账期与到期日</el-button>
    <div v-if="opened" v-loading="loading">
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <template v-if="data">
        <p>起算日期：{{data.anchor_date||'待确认'}} · 到期日期：{{data.due_date||'待确认'}} · {{statusLabel(data.status)}}</p>
        <p class="hint">{{data.message}} 到期日＝起算日期＋账期天数。未发生的节点不会按今天推算。</p>
        <el-form v-if="editable" label-position="top" :disabled="busy||disabled" class="terms-form" @submit.prevent>
          <el-form-item label="账期天数"><el-input-number v-model="form.days" :min="0" :max="3650" :precision="0" placeholder="未约定"/></el-form-item>
          <el-form-item label="起算方式"><el-select v-model="form.start"><el-option v-for="(label,value) in starts" :key="value" :value="value" :label="label"/></el-select></el-form-item>
          <el-form-item label="提前提醒天数"><el-input-number v-model="form.reminder_days" :min="0" :max="365" :precision="0"/></el-form-item>
          <el-form-item v-if="form.start==='reconciliation_date'" label="对账确认日期"><el-date-picker v-model="form.reconciliation_date" type="date" value-format="YYYY-MM-DD" clearable/></el-form-item>
          <el-form-item label="约定到期日（选填，优先于公式）"><el-date-picker v-model="form.due_date_override" type="date" value-format="YYYY-MM-DD" clearable/></el-form-item>
          <el-form-item label="调整原因（必填）"><el-input v-model="form.reason" type="textarea" maxlength="1000"/></el-form-item>
          <el-button type="primary" :loading="busy" @click="save">保存本单账期</el-button>
        </el-form>
        <p class="hint">本单调整保留记录，不改变档案默认值、费用或付款金额。清空约定到期日后，恢复按起算事件计算。</p>
        <details v-if="data.history?.length"><summary>查看调整记录</summary><div v-for="(item,index) in data.history" :key="item.id||index">{{item.created_at}} · {{item.reason||item.payload?.reason||'账期调整'}}</div></details>
      </template>
    </div>
  </section>
</template>
<script setup>
import {computed,onUnmounted,reactive,ref,watch} from 'vue';
import * as api from '../../api/paymentTermsV2';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
const props=defineProps({kind:String,id:[String,Number],disabled:Boolean,refreshVersion:[String,Number]});
const emit=defineEmits(['updated']);
const auth=useAuthStore(),editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage'));
const opened=ref(false),loading=ref(false),busy=ref(false),error=ref(''),data=ref(null);
const form=reactive({days:null,start:'unspecified',reminder_days:7,reconciliation_date:null,due_date_override:null,reason:''});
const starts={unspecified:'未约定',shipment_date:'供应商发货日',collection_arrival:'集货到仓日',warehouse_arrival:'目的仓到仓日',reconciliation_date:'对账确认日'};
const statusLabel=value=>({overdue:'已逾期',due_soon:'即将到期',unknown:'待确认',settled:'已结清',scheduled:'未到提醒期'})[value]||'待核对';
let generation=0,attempt=null;
function unwrap(r){if(!r?.success)throw new Error(r?.message||'账期操作失败');return r.data;}
async function load(){const token=++generation;loading.value=true;error.value='';data.value=null;try{const result=unwrap(await api.fetchPaymentTerms(props.kind,props.id));if(token!==generation)return;data.value=result;Object.assign(form,{days:result.days??null,start:result.start||'unspecified',reminder_days:result.reminder_days??7,reconciliation_date:result.reconciliation_date||null,due_date_override:result.due_date_override||null,reason:''});}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
function toggle(){opened.value=!opened.value;if(opened.value)return load();generation++;loading.value=false;}
async function save(){if(!editable.value||busy.value||props.disabled||!data.value)return;if(!form.reason.trim()){error.value='请填写调整原因';return;}const kind=props.kind,id=props.id,token=generation;const body={...form,reason:form.reason.trim(),expected_version:data.value.version};const signature=JSON.stringify([kind,id,body]);if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};busy.value=true;error.value='';try{unwrap(await api.savePaymentTerms(kind,id,body,attempt.key));if(token!==generation)return;attempt=null;await load();emit('updated');}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
watch(()=>[props.kind,props.id],()=>{generation++;opened.value=false;data.value=null;error.value='';loading.value=false;attempt=null;});
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;opened.value=false;data.value=null;attempt=null;},{flush:'sync'});
watch(()=>props.refreshVersion,()=>{if(opened.value&&!busy.value)load();});
onUnmounted(()=>generation++);
defineExpose({toggle,load,save,form,data,error});
</script>
<style scoped>
.terms-panel{margin:14px 0;padding:12px;border:1px solid #dce4ef;border-radius:6px}.terms-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.hint{color:#64748b;font-size:13px;line-height:1.6}
</style>
