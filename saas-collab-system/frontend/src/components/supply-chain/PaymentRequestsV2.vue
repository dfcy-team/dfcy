<template>
  <section class="requests-panel">
    <el-button :disabled="busy||disabled" @click="toggle">{{opened?'收起付款申请与审批':'付款申请与审批'}}</el-button>
    <div v-if="opened" v-loading="loading">
      <p>申请 → 系统审批（飞书通知入口）。审批时上传转账凭证并填写付款日期；审批通过即生成付款记录并计入已付。历史已通过但未入账的申请仍可由财务确认入账。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <el-alert v-if="notice" :title="notice" type="info" :closable="false"/>
      <el-form v-if="editable" label-position="top" :disabled="busy||disabled" class="request-form" @submit.prevent>
        <el-form-item label="申请金额" required><el-input v-model="form.amount" inputmode="decimal"/></el-form-item>
        <el-form-item label="收款账户" required><el-select v-model="form.payee_account_id" filterable placeholder="选择所属供应商或货运公司账户"><el-option v-for="a in accounts.filter(a=>a.active)" :key="a.id" :value="a.id" :label="`${a.account_name} · ${natureLabel(a.nature)} · 尾号${String(a.account_number||'').slice(-4)}`"/></el-select></el-form-item>
        <el-form-item v-if="context.itemized" label="费用项目" required><el-select v-model="form.fee_item_id"><el-option v-for="item in context.fee_items||[]" :key="item.fee_item_id" :value="item.fee_item_id" :label="`${item.name} · 剩余 ${item.remaining_amount}`"/></el-select></el-form-item>
        <el-form-item label="申请理由" required><el-input v-model="form.reason" maxlength="1000"/></el-form-item>
        <el-button :disabled="busy||disabled" @click="create">保存付款申请草稿</el-button>
      </el-form>
      <div class="toolbar"><el-button :disabled="busy" @click="load">刷新审批与付款状态</el-button><el-button v-if="filterId" :disabled="busy" @click="showAll">查看本单全部申请</el-button></div>
      <el-table :data="rows" border empty-text="暂无付款申请">
        <el-table-column label="申请" width="90"><template #default="{row}">#{{row.id}}</template></el-table-column><el-table-column prop="amount" label="金额" width="120"/>
        <el-table-column label="收款账户" min-width="180"><template #default="{row}">{{row.account_snapshot?.account_name}} · {{natureLabel(row.account_snapshot?.nature)}}<small>尾号{{String(row.account_snapshot?.account_number||'').slice(-4)}}</small></template></el-table-column>
        <el-table-column label="状态 / 通知" min-width="150"><template #default="{row}">{{statusName(row.status)}}<small>{{notificationName(row.notification_status)}}</small><small v-if="row.notification_error">{{row.notification_error}}</small></template></el-table-column>
        <el-table-column prop="reason" label="申请理由" min-width="160"/>
        <el-table-column label="操作" min-width="230"><template #default="{row}"><router-link v-if="row.batch_href" :to="row.batch_href">查看批量付款</router-link><el-button v-if="row.can_submit" link :disabled="busy||disabled" @click="act(row,'submit')">提交审批</el-button><router-link v-if="row.approval_id" :to="`/workflow/approvals/${row.approval_id}`">查看审批</router-link><el-button v-if="row.can_notify" link :disabled="busy||disabled" @click="act(row,'notify')">重试飞书通知</el-button><el-button link :disabled="busy" @click="select(row)">凭证 / 入账详情</el-button><el-button v-if="row.can_cancel" link type="warning" :disabled="busy||disabled" @click="cancel(row)">取消申请</el-button></template></el-table-column>
      </el-table>
      <el-pagination layout="total,prev,pager,next" :total="total" :page-size="20" :current-page="page" :disabled="busy" @current-change="p=>{page=p;load()}"/>
      <section v-if="selected" class="selected-request"><h4>申请 #{{selected.id}} · {{statusName(selected.status)}} · {{selected.amount}}</h4><p>收款人：{{selected.account_snapshot?.account_holder}} · 银行：{{selected.account_snapshot?.bank_name}} · 账户：{{selected.account_snapshot?.account_number}}</p>
        <p>费用项目：{{selected.item_snapshot?.name || '整单款项'}} · 申请理由：{{selected.reason}}</p>
        <p v-if="selected.payment_id">已生成付款记录 #{{selected.payment_id}}，可在本页付款流水查看。</p>
        <div v-for="file in selected.vouchers||[]" :key="file.id">{{file.file_name}} <el-button link :disabled="busy" @click="preview(file)">预览</el-button><el-button link :disabled="busy" @click="download(file)">下载</el-button></div>
        <div v-if="selected.can_upload" class="upload"><label>转账凭证（PDF/JPG/PNG，每份10 MB，最多20份）<input type="file" accept=".pdf,.jpg,.jpeg,.png" :disabled="busy||disabled" @change="chooseFile"/></label><span v-if="chosenFile">{{chosenFile.name}}</span><el-button :disabled="busy||disabled||!chosenFile" @click="upload">上传凭证</el-button></div>
        <el-form v-if="selected.can_confirm" label-position="top" :disabled="busy||disabled" class="request-form"><el-form-item label="实际付款日期" required><el-date-picker v-model="payment.date" type="date" value-format="YYYY-MM-DD"/></el-form-item><el-form-item label="转账参考单号"><el-input v-model="payment.reference_number" maxlength="200"/></el-form-item><el-form-item label="付款备注"><el-input v-model="payment.notes" maxlength="1000"/></el-form-item><el-button type="primary" :disabled="busy||disabled||!payment.date||!selected.vouchers?.length" @click="confirmPayment">财务确认入账</el-button></el-form>
        <p v-else-if="selected.status==='approved'">历史申请已通过但尚未入账，请由具有财务权限的人员核对凭证后补充入账。</p>
      </section>
    </div>
    <el-dialog v-model="previewOpen" title="转账凭证" append-to-body width="min(1000px,95vw)" @closed="clearPreview"><img v-if="previewType.startsWith('image/')" :src="previewUrl" alt="转账凭证" class="preview-image"/><template v-else-if="previewUrl"><a :href="previewUrl" target="_blank" rel="noopener noreferrer">打开 PDF 凭证</a></template></el-dialog>
  </section>
</template>
<script setup>
import {computed,onMounted,onUnmounted,reactive,ref,watch} from 'vue';
import {useRoute} from 'vue-router';
import {ElMessageBox} from 'element-plus';
import {useAuthStore} from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import {amountUnits,natureLabel} from '../../utils/payeeSettlement';
import {fetchPayeeAccounts} from '../../api/supplyCostsV2';
import * as api from '../../api/paymentRequestsV2';
const props=defineProps({kind:String,id:[String,Number],context:{type:Object,default:()=>({})},disabled:Boolean}),emit=defineEmits(['updated']);
const auth=useAuthStore(),route=useRoute(),editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage'));
const opened=ref(false),busy=ref(false),loading=ref(false),error=ref(''),notice=ref(''),rows=ref([]),total=ref(0),page=ref(1),accounts=ref([]),selected=ref(null),filterId=ref(route?.query?.payment_request_id||null),chosenFile=ref(null);
const form=reactive({amount:'',payee_account_id:null,fee_item_id:null,reason:''}),payment=reactive({date:'',reference_number:'',notes:''});
const previewOpen=ref(false),previewUrl=ref(''),previewType=ref('');let generation=0,attempts=new Map(),fileAttempt=null;
const statusName=value=>({draft:'草稿',submitted:'待审批',pending:'待审批',approved:'已通过待付款',rejected:'已驳回',withdrawn:'已撤回',cancelled:'已取消',paid:'已入账',reversed:'已冲销'}[value]||value);
const notificationName=value=>({queued:'通知已入队（未代表送达）',no_matching_rule:'无匹配的飞书通知规则',error:'通知失败，可重试',failed:'通知失败，可重试',not_queued:'尚未通知',not_requested:'尚未通知'}[value]||value||'尚未通知');
function unwrap(r){if(!r?.success)throw new Error(r?.message||'付款申请操作失败');return r.data;}
async function load(){const token=++generation;loading.value=true;error.value='';try{const r=await api.fetchRequests(props.kind,props.id,{limit:20,offset:(page.value-1)*20,...(filterId.value?{request_id:filterId.value}:{})});const list=unwrap(r);if(token!==generation)return;rows.value=list;total.value=r.count||0;if(selected.value)selected.value=list.find(x=>x.id===selected.value.id)||null;if(filterId.value&&!selected.value&&list.length)select(list[0]);}catch(e){if(token===generation)error.value=e.message;}finally{if(token===generation)loading.value=false;}}
async function toggle(){if(busy.value||props.disabled)return;opened.value=!opened.value;if(!opened.value)return;await load();const token=generation;try{const value=unwrap(await fetchPayeeAccounts(props.kind,props.id));if(token===generation)accounts.value=value.accounts||[];}catch(e){if(token===generation)error.value=e.message;}}
function select(row){selected.value=row;chosenFile.value=null;fileAttempt=null;Object.assign(payment,{date:'',reference_number:'',notes:''});}
function showAll(){filterId.value=null;page.value=1;load();}
async function mutate(action,row,body){if(busy.value||props.disabled)return;const token=generation,id=props.id,kind=props.kind,signature=JSON.stringify([kind,id,row?.id,action,body]);if(!attempts.has(signature))attempts.set(signature,api.createIdempotencyKey());busy.value=true;error.value='';notice.value='';try{const r=action==='create'?await api.createRequest(kind,id,body,attempts.get(signature)):await api.requestAction(kind,id,row.id,action,body,attempts.get(signature));const value=unwrap(r);if(token!==generation)return;attempts.delete(signature);if(action==='create'){Object.assign(form,{amount:'',payee_account_id:null,fee_item_id:null,reason:''});page.value=1;filterId.value=null;}selected.value=value;await load();emit('updated');if(action==='submit'||action==='notify')notice.value=notificationName(value.notification_status);return value;}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
function create(){if(!editable.value)return;try{if(amountUnits(form.amount)<=0n||!form.payee_account_id||!form.reason.trim()||(props.context.itemized&&!form.fee_item_id))throw new Error('请填写有效金额、收款账户、申请理由及费用项目');return mutate('create',null,{amount:form.amount,payee_account_id:form.payee_account_id,...(form.fee_item_id?{fee_item_id:form.fee_item_id}:{}),reason:form.reason.trim()});}catch(e){error.value=e.message;}}
function act(row,action){if(!row[action==='submit'?'can_submit':'can_notify'])return;return mutate(action,row,{expected_version:row.version});}
async function cancel(row){if(!row.can_cancel)return;let result;try{result=await ElMessageBox.prompt('请输入取消原因；取消后不会生成付款。','取消付款申请',{inputValidator:v=>!!v?.trim()||'请输入原因'});}catch{return;}return mutate('cancel',row,{expected_version:row.version,reason:result.value.trim()});}
async function confirmPayment(){if(!selected.value?.can_confirm||!selected.value.vouchers?.length||!payment.date)return;try{await ElMessageBox.confirm(`确认已向此账户转账 ${selected.value.amount} 并将凭证登记入账？此操作用于历史已批准但未入账的申请。`,'财务确认');}catch{return;}return mutate('confirm',selected.value,{...payment,expected_version:selected.value.version});}
function chooseFile(event){const file=event.target.files?.[0];event.target.value='';chosenFile.value=null;fileAttempt=null;if(!file)return;if(!/\.(pdf|jpe?g|png)$/i.test(file.name)||file.size<=0||file.size>10*1024*1024){error.value='请选择10 MB以内的PDF/JPG/PNG文件';return;}chosenFile.value=file;}
async function upload(){if(busy.value||props.disabled||!selected.value?.can_upload||!chosenFile.value)return;const token=generation,row=selected.value,file=chosenFile.value;if(fileAttempt?.file!==file)fileAttempt={file,key:api.createIdempotencyKey()};busy.value=true;error.value='';try{const value=unwrap(await api.uploadVoucher(props.kind,props.id,row.id,file,fileAttempt.key));if(token!==generation)return;chosenFile.value=null;fileAttempt=null;selected.value=value;await load();}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
function clearPreview(){if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value='';previewType.value='';}
async function preview(file){if(busy.value)return;const token=generation;busy.value=true;try{const r=await api.previewVoucher(props.kind,props.id,selected.value.id,file);unwrap(r);if(token!==generation)return;clearPreview();previewUrl.value=URL.createObjectURL(r.blob);previewType.value=file.media_type;previewOpen.value=true;}catch(e){if(token===generation)error.value=e.message;}finally{busy.value=false;}}
async function download(file){if(busy.value)return;busy.value=true;try{unwrap(await api.downloadVoucher(props.kind,props.id,selected.value.id,file));}catch(e){error.value=e.message;}finally{busy.value=false;}}
watch(()=>[props.kind,props.id,cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{generation++;opened.value=false;rows.value=[];selected.value=null;accounts.value=[];chosenFile.value=null;fileAttempt=null;attempts.clear();Object.assign(form,{amount:'',payee_account_id:null,fee_item_id:null,reason:''});previewOpen.value=false;clearPreview();},{flush:'sync'});
onMounted(()=>{if(filterId.value)toggle();});onUnmounted(()=>{generation++;clearPreview();});
defineExpose({toggle,load,create,act,select,upload,confirmPayment,form,payment,rows,selected,error,chosenFile,opened});
</script>
<style scoped>
.requests-panel{border:1px solid #dce3ed;padding:14px;border-radius:8px;margin:16px 0}.requests-panel p,.requests-panel small{font-size:13px;line-height:1.6}.requests-panel small{display:block;color:#64748b}.request-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}.toolbar,.upload{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.selected-request{padding:14px;background:#f5f7fb;margin-top:14px;overflow-wrap:anywhere}.upload input{display:block;margin-top:8px}.preview-image{max-width:100%;max-height:75vh;display:block;margin:auto}@media(max-width:640px){.request-form{grid-template-columns:1fr}}
</style>
