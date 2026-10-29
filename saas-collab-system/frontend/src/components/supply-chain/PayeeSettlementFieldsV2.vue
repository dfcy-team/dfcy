<template>
  <section class="payee-fields">
    <div class="payee-heading"><strong>收款账户</strong><el-button v-if="editable || managerOnly" link type="primary" :disabled="disabled" @click="openManager">{{editable?'管理收款账户':'查看收款账户'}}</el-button></div>
    <p v-if="!managerOnly" class="hint">按收款账户登记累计金额，对公／对私由账户性质带入。已登记账户沿用历史性质；修改账户档案后，原结算快照保留。多个账户金额合计应等于上方累计已结算金额。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-for="(row,index) in (managerOnly ? [] : modelValue)" :key="index" class="payee-row">
      <el-select :model-value="row.account_id" :disabled="!editable || disabled" filterable placeholder="选择收款账户" @update:model-value="value=>change(index,{account_id:value})" @visible-change="v=>{if(v)loadAccounts()}">
        <el-option v-for="account in rowOptions(row)" :key="account.id" :value="account.id" :label="accountLabel(account)" :disabled="!account.active && account.id !== row.account_id" />
      </el-select>
      <span>{{ natureLabel(selectedAccount(row)?.nature) }}</span>
      <el-input :model-value="row.amount" :disabled="!editable || disabled" inputmode="decimal" placeholder="该账户累计金额" aria-label="收款账户累计金额" @update:model-value="value=>change(index,{amount:value})" />
      <el-button v-if="editable" link type="danger" :disabled="disabled" @click="remove(index)">移除</el-button>
    </div>
    <p v-if="!managerOnly && !modelValue.length" class="hint">尚未指定收款账户；历史记录保留未标识。</p>
    <el-button v-if="editable && !managerOnly" :disabled="disabled" @click="add">添加收款账户</el-button>
    <el-dialog v-model="managerOpen" title="收款账户管理" width="min(720px,96vw)" append-to-body>
      <p>账户归属于本单据对应的供应商或货运公司。历史结算保存账户快照。</p>
      <el-alert v-if="managerError" :title="managerError" type="error" :closable="false" />
      <el-table :data="accounts" border>
        <el-table-column prop="account_name" label="账户名称" />
        <el-table-column label="性质"><template #default="{row}">{{ natureLabel(row.nature) }}</template></el-table-column>
        <el-table-column prop="account_holder" label="收款户名" />
        <el-table-column label="银行／尾号"><template #default="{row}">{{ row.bank_name }} · {{ String(row.account_number||'').slice(-4) }}</template></el-table-column>
        <el-table-column v-if="editable" label="操作"><template #default="{row}"><el-button link :disabled="saving" @click="edit(row)">编辑</el-button></template></el-table-column>
      </el-table>
      <el-button v-if="editable" link type="primary" :disabled="saving" @click="edit()">新增账户</el-button>
      <el-form v-if="editable" :disabled="saving" label-position="top" class="account-form" @submit.prevent>
        <el-form-item label="账户名称" required><el-input v-model="form.account_name" maxlength="100" /></el-form-item>
        <el-form-item label="账户性质" required><el-select v-model="form.nature"><el-option value="corporate" label="对公"/><el-option value="personal" label="对私"/></el-select></el-form-item>
        <el-form-item label="收款户名" required><el-input v-model="form.account_holder" maxlength="160" /></el-form-item>
        <el-form-item label="开户银行" required><el-input v-model="form.bank_name" maxlength="160" /></el-form-item>
        <el-form-item label="收款账号" required><el-input v-model="form.account_number" maxlength="100" autocomplete="off" /></el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.active" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="managerOpen=false">关闭</el-button><el-button v-if="editable" type="primary" :loading="saving" @click="saveAccount">{{ form.id ? '保存账户修改' : '新增账户' }}</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { onUnmounted, reactive, ref, watch } from 'vue';
import * as api from '../../api/supplyCostsV2';
import { natureLabel } from '../../utils/payeeSettlement';
const props=defineProps({kind:String,id:[String,Number],modelValue:{type:Array,default:()=>[]},total:[String,Number],editable:Boolean,disabled:Boolean,managerOnly:Boolean});
const emit=defineEmits(['update:modelValue','accounts-changed']);
const accounts=ref([]),error=ref(''),managerError=ref(''),managerOpen=ref(false),saving=ref(false);
const blank=()=>({id:null,version:0,account_name:'',nature:'corporate',account_holder:'',bank_name:'',account_number:'',active:true});
const form=reactive(blank());let generation=0,loaded=false,loadingPromise=null,writeAttempt=null;
function unwrap(result){if(!result?.success)throw new Error(result?.message||'收款账户读取失败');return result.data;}
async function loadAccounts(force=false){
  if(loaded&&!force)return;
  if(loadingPromise&&!force)return loadingPromise;
  const token=++generation,kind=props.kind,id=props.id;
  loadingPromise=(async()=>{try{const data=unwrap(await api.fetchPayeeAccounts(kind,id));if(token===generation){accounts.value=data.accounts||data.results||[];loaded=true;error.value='';}}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loadingPromise=null;}})();
  return loadingPromise;
}
function selectedAccount(row){return row.account_snapshot||accounts.value.find(a=>String(a.id)===String(row.account_id));}
function accountLabel(account){return `${account.account_name||account.account_holder||'历史账户'} · ${natureLabel(account.nature)} · ${account.bank_name||''} · 尾号${String(account.account_number||account.account_number_last4||'').slice(-4)}${account.active===false?'（已停用）':''}`;}
function rowOptions(row){const list=accounts.value.filter(a=>a.active&&String(a.id)!==String(row.account_id));if(row.account_id)list.push({...selectedAccount(row),id:row.account_id});return list;}
function change(index,patch){emit('update:modelValue',props.modelValue.map((r,i)=>i===index?{...r,...patch,account_snapshot:patch.account_id&&String(patch.account_id)!==String(r.account_id)?accounts.value.find(a=>String(a.id)===String(patch.account_id)):r.account_snapshot}:r));}
function remove(index){emit('update:modelValue',props.modelValue.filter((_,i)=>i!==index));}
function add(){loadAccounts();emit('update:modelValue',[...props.modelValue,{account_id:null,amount:props.modelValue.length?'':String(props.total||''),account_snapshot:null}]);}
function edit(row){Object.assign(form,row?{...blank(),...row}:blank());managerError.value='';writeAttempt=null;}
async function openManager(){managerOpen.value=true;edit();await loadAccounts(true);}
async function saveAccount(){
  if(!props.editable||props.disabled||saving.value)return;
  const kind=props.kind,id=props.id;
  managerError.value='';
  if(['account_name','account_holder','bank_name','account_number'].some(k=>!String(form[k]).trim())){managerError.value='请填写账户名称、收款户名、开户银行和账号';return;}
  saving.value=true;
  try{const body={...form,expected_version:form.version};delete body.id;delete body.version;if(!form.id)delete body.expected_version;const signature=JSON.stringify([kind,id,form.id,body]);if(writeAttempt?.signature!==signature)writeAttempt={signature,key:api.createIdempotencyKey()};await (form.id?api.updatePayeeAccount(kind,id,form.id,body,writeAttempt.key):api.createPayeeAccount(kind,id,body,writeAttempt.key)).then(unwrap);if(kind!==props.kind||id!==props.id)return;writeAttempt=null;await loadAccounts(true);emit('accounts-changed');edit();}
  catch(e){managerError.value=e.message;}finally{saving.value=false;}
}
watch(()=>props.total,(value,previous)=>{if(props.editable&&props.modelValue.length===1&&String(props.modelValue[0].amount)===String(previous))change(0,{amount:String(value||'')});});
watch(()=>[props.kind,props.id],()=>{generation++;accounts.value=[];loaded=false;loadingPromise=null;error.value='';managerOpen.value=false;writeAttempt=null;});
onUnmounted(()=>{generation++;});
defineExpose({loadAccounts,add,change,saveAccount,openManager,form,accounts,selectedAccount,rowOptions});
</script>
<style scoped>
.payee-fields{margin:16px 0;padding:16px;border:1px solid #e2e8f0;border-radius:6px}.payee-heading{display:flex;justify-content:space-between;align-items:center}.hint{color:#64748b;font-size:13px;line-height:1.6}.payee-row{display:grid;grid-template-columns:minmax(220px,2fr) 80px minmax(140px,1fr) 50px;gap:12px;align-items:center;margin:12px 0}.account-form{display:grid;grid-template-columns:1fr 1fr;gap:0 16px;margin-top:16px}@media(max-width:640px){.payee-row,.account-form{grid-template-columns:1fr}.payee-row{padding:12px 0;border-bottom:1px solid #e2e8f0}}
</style>
