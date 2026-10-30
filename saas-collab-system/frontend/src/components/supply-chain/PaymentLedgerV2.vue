<template>
  <section class="payment-panel" v-loading="loading">
    <header><h3>{{({purchase:'采购定金',shipment:'供应商货款付款',batch:'批次货运付款',domestic_freight:'国内运费付款'})[kind]||'付款与抵扣'}}</h3><el-button :disabled="busy" @click="load">刷新付款记录</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="data">
      <nav class="source-links"><router-link v-for="link in (data.target?.source_links||[])" :key="link.href" :to="link.href">{{link.label}}</router-link></nav>
      <div class="payment-summary">
        <div><small>{{kind==='purchase'?'采购总额':'应付金额'}}</small><strong>{{display(data.summary.due_amount)}}</strong></div>
        <div><small>{{kind==='purchase'?'已付定金':'累计已付（含历史）'}}</small><strong>{{display(data.summary.paid_amount)}}</strong></div>
        <div v-if="kind==='purchase'||kind==='shipment'"><small>{{kind==='purchase'?'已抵扣':'定金抵扣'}}</small><strong>{{display(data.summary.applied_amount)}}</strong></div>
        <div><small>{{kind==='purchase'?'定金余额':'剩余应付'}}</small><strong>{{display(kind==='purchase'?data.summary.available_prepayment:data.summary.remaining_amount)}}</strong></div>
      </div>
      <el-alert v-if="data.summary.due_amount!=null && Number(data.summary.paid_amount)+Number(kind==='purchase'?0:data.summary.applied_amount)>Number(data.summary.due_amount)" title="已付及抵扣高于当前应付，请核对历史登记或单据金额变化。" type="warning" :closable="false" />
      <p v-if="kind==='purchase'" class="hint">未付采购金额：{{display(data.summary.remaining_amount)}}。定金抵扣发货单后不重复计算付款；不同批次共用本采购单的剩余定金余额。</p>
      <p v-if="Number(data.summary.opening_amount)>0" class="hint">历史累计已结算 {{display(data.summary.opening_amount)}} 已作为期初计入，历史各版本不再累加。历史凭证在下方历史结算中查看。</p>
      <p class="hint">仅登记已发生的转账，不执行付款，也不改变商品成本。对公／对私由收款账户带入。</p>
      <template v-if="editable">
        <el-form label-position="top" :disabled="busy || disabled" class="payment-form" @submit.prevent>
          <el-form-item :label="kind==='purchase'?'本次定金金额':'本次付款金额'" required><el-input v-model="form.amount" inputmode="decimal" placeholder="填写本次金额，不填累计金额" /></el-form-item>
          <el-form-item label="付款日期" required><el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="收款账户" required><el-select v-model="form.payee_account_id" placeholder="选择收款账户" filterable @visible-change="v=>v&&loadAccounts()"><el-option v-for="a in accounts.filter(a=>a.active)" :key="a.id" :value="a.id" :label="`${a.account_name} · ${natureLabel(a.nature)} · 尾号${String(a.account_number||'').slice(-4)}`"/></el-select></el-form-item>
          <el-form-item label="备注（选填）"><el-input v-model="form.notes" maxlength="10000" /></el-form-item>
        </el-form>
        <PayeeSettlementFieldsV2 :kind="kind" :id="id" manager-only :editable="editable" :disabled="busy||disabled" @accounts-changed="loadAccounts(true)" />
        <el-button type="primary" :disabled="busy||disabled" :loading="busy" @click="save">{{kind==='purchase'?'登记本次定金':'登记本次付款'}}</el-button>
        <p class="hint">保存付款后，在该笔记录中上传 PDF / JPG / PNG 凭证；未上传会显示“待上传凭证”。</p>
        <section v-if="kind==='shipment' && data.available_prepayments?.length" class="application">
          <h4>抵扣关联采购单定金</h4><div class="payment-form">
            <el-select v-model="application.payment_id" :disabled="busy||disabled" placeholder="选择可用定金"><el-option v-for="p in data.available_prepayments" :key="p.id" :value="p.id" :label="`${p.reference_number || p.id} · 可用 ${p.available_amount}`"/></el-select>
            <el-input v-model="application.amount" :disabled="busy||disabled" inputmode="decimal" placeholder="本次抵扣金额" />
            <el-date-picker v-model="application.date" :disabled="busy||disabled" type="date" value-format="YYYY-MM-DD" placeholder="抵扣日期" />
            <el-button :disabled="busy||disabled" @click="apply">确认抵扣</el-button>
          </div>
        </section>
      </template>
      <p class="hint">{{data.process_basis}}</p>
      <el-table :data="(data.entries || []).slice((historyPage-1)*20,historyPage*20)" border class="payment-history" empty-text="暂无逐笔付款记录">
        <el-table-column prop="sequence" label="顺序" width="65"/><el-table-column prop="reference_number" label="记录单号" min-width="170"/>
        <el-table-column prop="date" label="业务日期" width="110"/><el-table-column label="登记时间" min-width="170"><template #default="{row}">{{row.recorded_at?new Date(row.recorded_at).toLocaleString('zh-CN',{hour12:false}):'历史期初'}}</template></el-table-column>
        <el-table-column label="类型" width="100"><template #default="{row}">{{row.entry_type==='opening'?'历史期初':row.entry_type==='application'?'定金抵扣':kind==='purchase'?'定金':'付款'}}<el-tag v-if="row.reversed" type="info">已冲销</el-tag><el-tag v-if="row.is_reversal" type="info">冲销记录</el-tag></template></el-table-column>
        <el-table-column prop="amount" label="本次金额" min-width="120"/>
        <el-table-column prop="cash_change" label="付款增减" min-width="120"/>
        <el-table-column v-if="kind==='purchase'||kind==='shipment'" prop="application_change" label="抵扣增减" min-width="120"/>
        <el-table-column prop="paid_after" label="本行后累计已付" min-width="145"/>
        <el-table-column prop="remaining_after" label="本行后未付（当前应付口径）" min-width="210"/>
        <el-table-column v-if="kind==='purchase'" prop="available_after" label="本行后定金余额" min-width="150"/>
        <el-table-column label="关联单据" min-width="175"><template #default="{row}"><router-link v-if="row.related_href" :to="row.related_href">{{row.related_number}}</router-link><router-link v-else-if="row.source_kind==='purchase'" :to="`/supply-chain/costs?kind=purchase&id=${row.source_id}`">查看原定金</router-link><span v-else>—</span></template></el-table-column>
        <el-table-column label="收款账户" min-width="170"><template #default="{row}">{{row.account_snapshot?.account_name||row.account_snapshot?.account_holder||'—'}}<small class="account-nature">{{natureLabel(row.account_snapshot?.nature)}}</small></template></el-table-column>
        <el-table-column label="备注／更正原因" min-width="150"><template #default="{row}">{{row.reversal_reason || row.notes || '—'}}</template></el-table-column>
        <el-table-column label="付款凭证" min-width="200"><template #default="{row}">
          <template v-if="row.entry_type==='payment'">
            <el-button v-for="v in (row.attachments||[])" :key="v.id" link @click="download(row,v)">{{v.file_name}}</el-button>
            <span v-if="!row.attachments?.length" class="hint">待上传凭证</span>
            <label v-if="editable && !row.is_reversal && !row.reversed" class="upload-label">上传凭证<input type="file" accept=".pdf,.jpg,.jpeg,.png" :disabled="busy||disabled" @change="upload(row,$event)"/></label>
          </template><span v-else-if="row.entry_type==='application'">沿用原定金凭证<el-button v-for="v in (row.attachments||[])" :key="v.id" link @click="download(row,v)">{{v.file_name}}</el-button></span>
        </template></el-table-column>
        <el-table-column v-if="editable" label="更正" width="110"><template #default="{row}"><el-button v-if="row.entry_type!=='opening' && !row.reversed && !row.is_reversal && !(kind==='purchase' && row.entry_type==='application')" link type="danger" :disabled="busy||disabled" @click="reverse(row)">{{row.entry_type==='application'?'撤销抵扣':'冲销付款'}}</el-button></template></el-table-column>
      </el-table><el-pagination v-if="data.entries?.length>20" v-model:current-page="historyPage" :total="data.entries.length" :page-size="20" layout="total,prev,pager,next"/>
    </template>
  </section>
</template>
<script setup>
import {computed,onUnmounted,reactive,ref,watch} from 'vue';
import {ElMessage,ElMessageBox} from 'element-plus';
import {useAuthStore} from '../../stores/auth';
import * as api from '../../api/supplyCostsV2';
import {downloadApiFile} from '../../api/request';
import {amountUnits,natureLabel} from '../../utils/payeeSettlement';
import PayeeSettlementFieldsV2 from './PayeeSettlementFieldsV2.vue';
const props=defineProps({kind:{type:String,required:true},id:{type:[String,Number],required:true},disabled:Boolean,refreshVersion:[String,Number]});
const emit=defineEmits(['updated']);
const auth=useAuthStore(),editable=computed(()=>!auth.authorizationStale&&auth.hasPermission('supply.v2.manage'));
const historyPage=ref(1);
const data=ref(null),error=ref(''),loading=ref(false),busy=ref(false),accounts=ref([]);
const today=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const form=reactive({amount:'',date:today(),payee_account_id:null,notes:''}),application=reactive({payment_id:null,amount:'',date:today()});
let generation=0,documentGeneration=0,accountGeneration=0,accountsLoaded=false,attempt=null,uploadAttempt=null;
const display=v=>v==null?'待核对':v;
function unwrap(r){if(!r?.success){const details=r?.data;throw new Error(`${r?.message||'付款数据读取失败'}${details?'：'+JSON.stringify(details):''}`);}return r.data;}
function message(e){const details=e.response?.data?.data;return details?`${e.response?.data?.message||e.message}：${JSON.stringify(details)}`:e.message;}
async function load(){const token=++generation,kind=props.kind,id=props.id;loading.value=true;error.value='';try{const result=unwrap(await api.fetchPayments(kind,id));if(!result?.summary)throw new Error('付款接口未返回汇总信息，请确认后端版本');if(token===generation)data.value=result;}catch(e){if(token===generation)error.value=message(e);}finally{if(token===generation)loading.value=false;}}
async function loadAccounts(force=false){if(accountsLoaded&&!force)return;const token=++accountGeneration;try{const result=unwrap(await api.fetchPayeeAccounts(props.kind,props.id));if(token===accountGeneration){accounts.value=result.accounts||[];accountsLoaded=true;}}catch(e){if(token===accountGeneration)error.value=message(e);}}
function positive(value){if(amountUnits(value)<=0n)throw new Error('金额必须大于零');return String(value).trim();}
async function mutate(action,body){
 if(busy.value||props.disabled||!editable.value)return;
 const kind=props.kind,id=props.id,token=documentGeneration;const signature=JSON.stringify([kind,id,action,body]);
 if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};
 busy.value=true;error.value='';
 try{unwrap(await (action==='payment'?api.createPayment(kind,id,body,attempt.key):api.applyPrepayment(id,body,attempt.key)));if(token!==documentGeneration||kind!==props.kind||id!==props.id)return;attempt=null;form.amount='';form.notes='';application.amount='';application.payment_id=null;await load();emit('updated');ElMessage.success(action==='payment'?'付款已登记，请上传付款凭证':'定金已抵扣');}
 catch(e){if(token===documentGeneration)error.value=message(e);}finally{busy.value=false;}
}
async function save(){try{if(!data.value)throw new Error('请先读取付款信息');const amount=positive(form.amount);if(!form.date)throw new Error('请选择付款日期');if(!form.payee_account_id)throw new Error('请选择收款账户');await mutate('payment',{amount,date:form.date,payee_account_id:form.payee_account_id,notes:form.notes,expected_version:data.value.version});}catch(e){error.value=message(e);}}
async function apply(){try{const amount=positive(application.amount);if(!application.payment_id||!application.date)throw new Error('请选择定金和抵扣日期');await mutate('application',{payment_id:application.payment_id,amount,date:application.date,expected_version:data.value.version});}catch(e){error.value=message(e);}}
async function upload(row,event){const file=event.target.files?.[0];event.target.value='';if(!file||busy.value||props.disabled||!editable.value)return;const kind=props.kind,id=props.id,token=documentGeneration;const signature=JSON.stringify([kind,id,row.id,file.name,file.size,file.lastModified]);if(uploadAttempt?.signature!==signature)uploadAttempt={signature,key:api.createIdempotencyKey()};busy.value=true;try{unwrap(await api.uploadPaymentVoucher(kind,id,row.id,file,uploadAttempt.key));if(token!==documentGeneration)return;uploadAttempt=null;await load();}catch(e){if(token===documentGeneration)error.value=message(e);}finally{busy.value=false;}}
async function reverse(row){
 if(busy.value||props.disabled||!editable.value)return;
 const kind=props.kind,id=props.id,token=documentGeneration;
 try{
  const answer=await ElMessageBox.prompt('请填写更正原因。原记录保留；已抵扣的定金须先撤销抵扣。','确认冲销',{inputPattern:/\S+/,inputErrorMessage:'请填写原因',confirmButtonText:'确认冲销',cancelButtonText:'取消'});
  if(token!==documentGeneration||kind!==props.kind||id!==props.id)return;
  const body={reason:answer.value.trim(),expected_version:data.value.version},signature=JSON.stringify([kind,id,'reverse',row.entry_type,row.id,body]);
  if(attempt?.signature!==signature)attempt={signature,key:api.createIdempotencyKey()};
  busy.value=true;
  unwrap(await (row.entry_type==='application'?api.reversePrepayment(id,row.id,body,attempt.key):api.reversePayment(kind,id,row.id,body,attempt.key)));
  if(token!==documentGeneration)return;
  attempt=null;await load();emit('updated');ElMessage.success('已冲销，原记录保留供核对');
 }catch(e){if(e!=='cancel'&&e!=='close'&&token===documentGeneration)error.value=message(e);}finally{busy.value=false;}
}
async function download(row,voucher){try{await downloadApiFile(api.paymentVoucherUrl(row.source_kind||props.kind,row.source_id||props.id,row.payment_id||row.id,voucher.id),voucher.file_name);}catch(e){error.value=message(e);}}
watch(()=>[props.kind,props.id],()=>{generation++;documentGeneration++;accountGeneration++;data.value=null;historyPage.value=1;accounts.value=[];accountsLoaded=false;attempt=null;uploadAttempt=null;Object.assign(form,{amount:'',date:today(),payee_account_id:null,notes:''});Object.assign(application,{payment_id:null,amount:'',date:today()});load();},{immediate:true});
watch(()=>props.refreshVersion,()=>load());
onUnmounted(()=>{generation++;documentGeneration++;accountGeneration++;});
defineExpose({load,save,apply,reverse,loadAccounts,form,application,data,error});
</script>
<style scoped>
.source-links{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}.source-links a{font-size:13px;color:#2563eb}.payment-panel{margin:20px 0;padding:18px;border:1px solid #dce3ed;border-radius:8px}.payment-panel header{display:flex;align-items:center;justify-content:space-between;gap:12px}.payment-panel h3{margin:0 0 12px}.payment-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0}.payment-summary>div{padding:12px;background:#f5f7fb;border-radius:6px}.payment-summary small,.payment-summary strong,.account-nature{display:block}.payment-summary strong{margin-top:8px;font-size:18px;overflow-wrap:anywhere}.payment-form{display:grid;grid-template-columns:1fr 1fr;gap:12px}.payment-form :deep(.el-select),.payment-form :deep(.el-date-editor){width:100%}.hint{color:#64748b;font-size:13px;line-height:1.6}.application{margin:18px 0}.payment-history{margin-top:18px}.upload-label{display:inline-block;position:relative;color:#2563eb;margin:6px;cursor:pointer}.upload-label input{position:absolute;inset:0;opacity:0;width:100%;cursor:pointer}@media(max-width:640px){.payment-summary,.payment-form{grid-template-columns:1fr 1fr}.payment-panel{padding:12px}.payment-panel header{align-items:start}}
</style>
