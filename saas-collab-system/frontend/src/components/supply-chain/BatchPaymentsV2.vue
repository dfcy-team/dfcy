<template>
<section class="batch-payments">
  <h3>批量付款 · {{partyName || (partyKind==='supplier'?'供应商':'货运方')}}</h3>
  <p>同一往来单位、收款账户及对公／对私性质合并申请。审批时上传转账凭证并核对付款日期，通过后自动逐单入账。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <template v-if="partyId && editable">
    <div class="toolbar"><el-input v-model="search" placeholder="搜索单据" @keyup.enter="page=1;loadCandidates()"/><el-button :disabled="busy" @click="page=1;loadCandidates()">查询待付单据</el-button><el-button :disabled="busy" @click="selected={}">清空选择</el-button></div>
    <el-table :data="rows" border v-loading="loading">
      <el-table-column label="选择" width="65"><template #default="{row}"><el-checkbox :model-value="!!selected[keyOf(row)]" :disabled="busy || Number(row.available_amount)<=0" @change="value=>choose(row,value)"/></template></el-table-column>
      <el-table-column prop="number" label="单据" min-width="150"/><el-table-column prop="fee_item_name" label="费用项目" min-width="110"/>
      <el-table-column label="性质"><template #default="{row}">{{nature(row.nature)}}</template></el-table-column>
      <el-table-column prop="due_amount" label="应付"/><el-table-column prop="paid_amount" label="已付"/><el-table-column prop="reserved_amount" label="审批占用"/><el-table-column prop="available_amount" label="可申请"/>
    </el-table><el-pagination :current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" @current-change="p=>{page=p;loadCandidates()}"/>
    <h4>已选择 {{picked.length}} 项（最多20项，翻页保留） · 本次合计 {{sum}}</h4>
    <el-table v-if="picked.length" :data="picked" border><el-table-column prop="number" label="单据"/><el-table-column prop="fee_item_name" label="项目"/><el-table-column label="本次付款"><template #default="{row}"><el-input v-model="row.amount" inputmode="decimal" :disabled="busy"/></template></el-table-column><el-table-column label="操作"><template #default="{row}"><el-button link :disabled="busy" @click="choose(row,false)">移除</el-button></template></el-table-column></el-table>
    <div class="toolbar"><el-select v-model="accountId" placeholder="统一收款账户" :disabled="busy"><el-option v-for="a in accounts" :key="a.id" :value="a.id" :label="`${a.account_name || a.account_holder} · ${nature(a.nature)} · ${a.account_number}`"/></el-select><el-input v-model="reason" placeholder="申请理由" maxlength="1000" :disabled="busy"/><el-button type="primary" :disabled="busy||picked.length<2" @click="save">保存批量申请</el-button></div>
  </template>
  <h4>批量付款申请</h4><el-button :disabled="busy" @click="loadHistory">刷新</el-button>
  <el-table :data="history" border><el-table-column prop="id" label="申请编号"/><el-table-column prop="amount" label="金额"/><el-table-column label="状态"><template #default="{row}">{{status(row.status)}}</template></el-table-column><el-table-column label="操作"><template #default="{row}"><el-button link :disabled="busy" @click="open(row.id)">查看 / 审批 / 凭证</el-button></template></el-table-column></el-table>
  <el-pagination :current-page="historyPage" :total="historyTotal" :page-size="20" layout="total,prev,pager,next" @current-change="p=>{historyPage=p;loadHistory()}"/>
  <section v-if="current" class="detail">
    <h4>申请 #{{current.id}} · {{status(current.status)}} · {{current.amount}}</h4>
    <p>{{current.account_snapshot?.account_holder}} · {{current.account_snapshot?.bank_name}} · {{current.account_snapshot?.account_number}} · {{nature(current.account_snapshot?.nature)}}</p><p>{{current.reason}}</p>
    <el-table :data="current.lines||[]" border><el-table-column prop="number" label="来源单据"/><el-table-column prop="amount" label="申请金额"/><el-table-column label="查看"><template #default="{row}"><router-link :to="`/supply-chain/costs?kind=${row.kind}&id=${row.source_id}`">单据及付款流水</router-link></template></el-table-column></el-table>
    <div class="toolbar"><el-button v-if="current.can_submit" :disabled="busy" @click="act('submit')">提交审批</el-button><router-link v-if="current.approval_id" :to="`/workflow/approvals/${current.approval_id}`">查看审批</router-link><el-button v-if="current.can_cancel" :disabled="busy" @click="reasonAction('cancel')">取消申请</el-button><el-button v-if="current.can_notify" :disabled="busy" @click="act('notify')">重试飞书通知</el-button><el-button v-if="current.can_reverse" type="danger" :disabled="busy" @click="reasonAction('reverse')">冲销整组付款</el-button></div>
    <p v-if="current.notification_error">{{current.notification_error}}</p>
    <div v-for="file in current.vouchers||[]" :key="file.id">{{file.file_name}} <el-button link :disabled="busy" @click="download(file)">下载凭证</el-button></div>
    <label v-if="current.can_upload">上传转账凭证（PDF/JPG/PNG，单份10MB，最多5份）<input type="file" accept=".pdf,.jpg,.jpeg,.png" :disabled="busy" @change="upload"/></label>
    <div v-if="current.can_confirm" class="toolbar"><el-date-picker v-model="payment.date" type="date" value-format="YYYY-MM-DD" placeholder="实际付款日期"/><el-input v-model="payment.reference_number" placeholder="转账参考单号"/><el-button type="primary" :disabled="busy||!payment.date" @click="confirm">财务确认整组入账</el-button></div>
  </section>
</section>
</template>
<script setup>
import {computed,reactive,ref,watch,onUnmounted} from 'vue';
import {ElMessageBox} from 'element-plus';
import {useAuthStore} from '../../stores/auth';
import {amountUnits,natureLabel} from '../../utils/payeeSettlement';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import * as api from '../../api/paymentBatchesV2';
const props=defineProps({partyKind:String,partyId:[String,Number],partyName:String,requestId:[String,Number]}),emit=defineEmits(['updated']);
const auth=useAuthStore(),editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage'));
const rows=ref([]),total=ref(0),page=ref(1),search=ref(''),selected=ref({}),accounts=ref([]),accountId=ref(null),reason=ref(''),error=ref(''),loading=ref(false),busy=ref(false),history=ref([]),historyTotal=ref(0),historyPage=ref(1),current=ref(null),payment=reactive({date:'',reference_number:'',notes:''});
let generation=0,candidateGeneration=0,historyGeneration=0,detailGeneration=0;const attempts=new Map();const nature=v=>v?natureLabel(v):'按收款账户';
const status=v=>({draft:'草稿',pending:'待审批',submitted:'待审批',approved:'通过待付款',rejected:'驳回',withdrawn:'撤回',cancelled:'已取消',paid:'已入账',reversed:'已冲销'}[v]||v);
const keyOf=r=>`${r.kind}:${r.source_id}:${r.fee_item_id||''}`,picked=computed(()=>Object.values(selected.value));
const sum=computed(()=>{try{const units=picked.value.reduce((n,r)=>n+amountUnits(r.amount),0n);return `${units/10000n}.${String(units%10000n).padStart(4,'0')}`;}catch{return '金额待检查';}});
const params=()=>({...props.partyId?{party_kind:props.partyKind,party_id:props.partyId}:{},limit:20});
function data(r){if(!r?.success)throw new Error(r?.message||'付款操作失败');return r.data;}
async function loadCandidates(){if(!props.partyId)return;const token=generation,read=++candidateGeneration;loading.value=true;try{const r=await api.candidates({...params(),search:search.value,offset:(page.value-1)*20});const value=data(r);if(token!==generation||read!==candidateGeneration)return;rows.value=value;accounts.value=r.accounts||[];total.value=r.count||0;}catch(e){if(token===generation&&read===candidateGeneration)error.value=e.message;}finally{if(token===generation&&read===candidateGeneration)loading.value=false;}}
async function loadHistory(){const token=generation,read=++historyGeneration;try{const r=await api.list({...params(),offset:(historyPage.value-1)*20});const value=data(r);if(token!==generation||read!==historyGeneration)return;history.value=value;historyTotal.value=r.count||0;}catch(e){if(token===generation&&read===historyGeneration)error.value=e.message;}}
async function open(id){const token=generation,read=++detailGeneration;try{const value=data(await api.detail(id));if(token===generation&&read===detailGeneration)current.value=value;}catch(e){if(token===generation&&read===detailGeneration)error.value=e.message;}}
function choose(row,value){const key=keyOf(row);if(!value){delete selected.value[key];return;}if(picked.value.length>=20){error.value='每次最多选择20项';return;}selected.value[key]={...row,amount:row.available_amount};}
async function mutate(label,body,callback){if(busy.value||auth.authorizationStale)return;const token=generation,signature=JSON.stringify([props.partyKind,props.partyId,current.value?.id,label,body]);if(!attempts.has(signature))attempts.set(signature,api.createIdempotencyKey());busy.value=true;error.value='';try{const value=data(await callback(attempts.get(signature)));if(token!==generation)return;attempts.delete(signature);current.value=value;if(label==='create')selected.value={};await Promise.all([loadCandidates(),loadHistory()]);emit('updated');}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
function save(){if(!editable.value)return;try{if(picked.value.length<2)throw new Error('请至少选择两项付款明细');if(!accountId.value||!reason.value.trim())throw new Error('请选择收款账户并填写理由');const account=accounts.value.find(a=>a.id===accountId.value);for(const row of picked.value){if(amountUnits(row.amount)<=0n||amountUnits(row.amount)>amountUnits(row.available_amount))throw new Error(`${row.number} 本次金额超出可申请范围`);if(row.nature&&row.nature!==account?.nature)throw new Error('对公和对私项目请分别申请');}const body={payee_account_id:accountId.value,reason:reason.value.trim(),lines:picked.value.map(r=>({kind:r.kind,source_id:r.source_id,amount:r.amount,...r.fee_item_id?{fee_item_id:r.fee_item_id}:{}}))};return mutate('create',body,key=>api.create(body,key));}catch(e){error.value=e.message;}}
function act(action,extra={}){if(!current.value?.[`can_${action}`])return;const row=current.value,body={expected_version:row.version,...extra};return mutate(action,body,key=>api.action(row.id,action,body,key));}
async function reasonAction(action){try{const r=await ElMessageBox.prompt('请输入原因',action==='reverse'?'冲销整组付款':'取消批量申请',{inputValidator:v=>!!v?.trim()||'原因必填'});await act(action,{reason:r.value.trim()});}catch{}}
async function confirm(){try{await ElMessageBox.confirm(`确认已实际转账 ${current.value.amount}，并按明细整组入账？`,'财务确认');await act('confirm',{...payment});}catch{}}
async function upload(event){const file=event.target.files?.[0];event.target.value='';if(!file||!current.value?.can_upload)return;if(!/\.(pdf|jpe?g|png)$/i.test(file.name)||!file.size||file.size>10*1024*1024){error.value='请选择10MB以内PDF/JPG/PNG';return;}const row=current.value;await mutate('upload',{id:row.id,version:row.version,name:file.name,size:file.size,lastModified:file.lastModified},key=>api.upload(row,file,key));}
async function download(file){try{data(await api.download(current.value.id,file));}catch(e){error.value=e.message;}}
watch(()=>[props.partyKind,props.partyId,props.requestId,cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;candidateGeneration++;historyGeneration++;detailGeneration++;search.value='';payment.date='';payment.reference_number='';payment.notes='';total.value=0;historyTotal.value=0;loading.value=false;selected.value={};rows.value=[];history.value=[];accounts.value=[];current.value=null;accountId.value=null;reason.value='';error.value='';page.value=1;historyPage.value=1;attempts.clear();if(auth.authorizationStale)return;loadCandidates();loadHistory();if(props.requestId)open(props.requestId);},{immediate:true});
onUnmounted(()=>generation++);
defineExpose({save,choose,act,loadCandidates,open,selected,accountId,reason,error,current,rows});
</script>
<style scoped>.batch-payments{padding:16px;border:1px solid #dce4ef;border-radius:8px;margin:16px 0}.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}.toolbar :deep(.el-input),.toolbar :deep(.el-select){width:260px}.detail{background:#f5f7fb;padding:16px;margin-top:16px}.batch-payments p{color:#64748b;line-height:1.6}.el-pagination{margin:12px 0}</style>
