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
      <p v-if="kind==='shipment' && Number(data.summary.contract_tax_amount)>0" class="hint">应付已包含对公合同新增税费 {{data.summary.contract_tax_amount}}；其中计入商品成本 {{data.summary.contract_cost_tax_amount || '0.0000'}}（按合同退税／免税选择）。</p>
      <el-alert v-if="data.summary.due_amount!=null && Number(data.summary.paid_amount)+Number(kind==='purchase'?0:data.summary.applied_amount)>Number(data.summary.due_amount)" title="已付及抵扣高于当前应付，请核对历史登记或单据金额变化。" type="warning" :closable="false" />
      <div v-if="['batch','inbound'].includes(kind)&&data.itemized" class="fee-item-balances"><h4>{{kind==='inbound'?'入库清关分项余额':'批次费用分项余额'}}</h4><p v-for="item in data.fee_items" :key="item.fee_item_id">{{item.name}}（{{natureLabel(item.nature)}}）：应付 {{item.amount}} · 已付 {{item.paid_amount}} · 未付 {{item.remaining_amount}}</p></div>
      <p v-if="kind==='purchase'" class="hint">未付采购金额：{{display(data.summary.remaining_amount)}}。定金抵扣发货单后不重复计算付款；不同批次共用本采购单的剩余定金余额。</p>
      <p v-if="Number(data.summary.opening_amount)>0" class="hint">历史累计已结算 {{display(data.summary.opening_amount)}} 已作为期初计入，历史各版本不再累加。历史凭证在下方历史结算中查看。</p>
      <PaymentPlansPanelV2 v-if="['shipment','domestic_freight','batch'].includes(kind)" :kind="kind" :id="id" :disabled="busy||disabled" />
      <PaymentRequestsV2 :kind="kind" :id="id" :context="data" :disabled="busy||disabled" @updated="load();emit('updated')"/>
      <PaymentTermsPanelV2 v-if="kind!=='purchase'" :kind="kind" :id="id" :disabled="busy||disabled" :refresh-version="data.version" @updated="emit('updated')"/>
      <details class="payment-section"><summary>{{kind==='purchase'?'直接登记定金':kind==='shipment'?'直接登记已发生付款 / 定金抵扣':'直接登记已发生付款'}}</summary>
      <p class="hint">下方用于直接登记已发生的转账；通过上方付款申请确认入账的款项请勿重复登记。不执行实际转账，也不改变商品成本。对公／对私由收款账户带入。</p>
      <p class="hint">已提交且未入账的付款申请会占用可登记额度。若本次转账对应已有申请，请进入该申请的系统审批页上传凭证并核对付款，审批通过后自动入账；补录其他转账与已有申请冲突时，请先核对并处理原申请。</p>
      <el-alert v-if="kind==='shipment' && accounts.find(a=>a.id===form.payee_account_id)?.nature==='corporate'" title="本次为对公付款，请核对是否已签订采购合同；未签订请及时补签，当前付款登记仍可继续。" type="warning" :closable="false" />
      <template v-if="editable">
        <el-form label-position="top" :disabled="busy || disabled" class="payment-form" @submit.prevent>
          <el-form-item v-if="['batch','inbound'].includes(kind)&&data.itemized" label="费用项目" required><el-select v-model="form.fee_item_id" placeholder="选择本次付款所属项目"><el-option v-for="item in data.fee_items" :key="item.fee_item_id" :value="item.fee_item_id" :label="`${item.name} · 未付 ${item.remaining_amount} · ${natureLabel(item.nature)}`"/></el-select></el-form-item>
          <el-form-item label="本次付款币种" required><el-input v-model="form.currency" maxlength="3" placeholder="如 CNY、USD；按付款凭证确认"/></el-form-item>
          <el-form-item :label="kind==='purchase'?'本次定金金额':'本次付款金额'" required><el-input v-model="form.amount" inputmode="decimal" placeholder="填写本次金额，不填累计金额" /></el-form-item>
          <el-form-item label="付款日期" required><el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="收款账户" required><el-select v-model="form.payee_account_id" placeholder="选择收款账户" filterable @visible-change="v=>v&&loadAccounts()"><el-option v-for="a in accounts.filter(a=>a.active)" :key="a.id" :value="a.id" :label="`${a.account_name} · ${natureLabel(a.nature)} · 尾号${String(a.account_number||'').slice(-4)}`"/></el-select></el-form-item>
          <el-form-item label="备注（选填）"><el-input v-model="form.notes" maxlength="10000" /></el-form-item>
        </el-form>
        <PayeeSettlementFieldsV2 :kind="kind" :id="id" manager-only :editable="editable" :disabled="busy||disabled" @accounts-changed="loadAccounts(true)" />
        <el-button type="primary" :disabled="busy||disabled" :loading="busy" @click="save">{{kind==='purchase'?'登记本次定金':'登记本次付款'}}</el-button>
        <p class="hint">保存付款后，在该笔记录中上传 PDF / JPG / PNG 凭证；未上传会显示“待上传凭证”。</p>
        <section v-if="kind==='shipment' && (data.available_prepayments?.length || data.cross_prepayments?.length)" class="application">
          <h4>抵扣采购定金</h4>
          <el-checkbox v-if="data.cross_prepayments?.length" v-model="application.cross_order" :disabled="busy||disabled" @change="resetApplicationSource">使用同一供应商其他采购单的定金</el-checkbox>
          <p v-if="application.cross_order" class="hint">跨采购单抵扣会占用所选目标采购单的定金额度，请核对付款来源和当前发货单。</p>
          <div class="payment-form">
            <el-select v-model="application.payment_id" :disabled="busy||disabled" :placeholder="application.cross_order?'选择其他采购单的可用定金':'选择可用定金'"><el-option v-for="p in applicationPrepayments" :key="p.id" :value="p.id" :label="`${p.purchase_order_number ? p.purchase_order_number + ' · ' : ''}${p.reference_number || p.id} · 可用 ${p.available_amount}`"/></el-select>
            <el-select v-if="application.cross_order" v-model="application.target_purchase_order_id" :disabled="busy||disabled" placeholder="选择本次抵扣归属采购单"><el-option v-for="p in crossTargets" :key="p.purchase_order_id" :value="p.purchase_order_id" :label="`${p.purchase_order_number} · 可用应付额度 ${p.available_amount}`"/></el-select>
            <el-input v-model="application.amount" :disabled="busy||disabled" inputmode="decimal" placeholder="本次抵扣金额" />
            <el-date-picker v-model="application.date" :disabled="busy||disabled" type="date" value-format="YYYY-MM-DD" placeholder="抵扣日期" />
            <el-button :disabled="busy||disabled" @click="apply">确认抵扣</el-button>
          </div>
        </section>
      </template>
      </details>
      <details class="payment-section" open><summary>{{['purchase','shipment'].includes(kind)?'逐笔付款、抵扣与凭证流水':'逐笔付款与凭证流水'}}</summary>
      <p class="hint">{{data.process_basis}}</p>
      <p class="hint">筛选仅影响本单下方流水，上方余额仍为本单合计。待确认筛选排除冲销记录。<template v-if="['shipment','purchase'].includes(kind)">定金抵扣行也不列入待确认，抵扣性质请到原定金记录核对。</template></p>
      <el-form-item label="付款性质"><el-select v-model="classificationFilter" aria-label="筛选付款性质" @change="historyPage=1"><el-option value="all" label="全部性质"/><el-option value="unclassified" label="待确认（未冲销）"/><el-option value="corporate" label="对公（正报）"/><el-option value="personal" label="对私"/><el-option value="mixed" label="混合"/></el-select></el-form-item>
      <el-table :data="filteredEntries.slice((historyPage-1)*20,historyPage*20)" border class="payment-history" empty-text="当前筛选下暂无付款记录">
        <el-table-column prop="sequence" label="顺序" width="65"/><el-table-column prop="reference_number" label="记录单号" min-width="170"/>
        <el-table-column prop="date" label="业务日期" width="110"/><el-table-column label="登记时间" min-width="170"><template #default="{row}">{{row.recorded_at?new Date(row.recorded_at).toLocaleString('zh-CN',{hour12:false}):'历史期初'}}</template></el-table-column>
        <el-table-column label="类型" width="100"><template #default="{row}">{{row.entry_type==='opening'?'历史期初':row.entry_type==='application'?'定金抵扣':kind==='purchase'?'定金':'付款'}}<el-tag v-if="row.reversed" type="info">已冲销</el-tag><el-tag v-if="row.is_reversal" type="info">冲销记录</el-tag></template></el-table-column>
        <el-table-column v-if="['batch','inbound'].includes(kind)" label="费用项目" min-width="130"><template #default="{row}">{{row.item_snapshot?.name || '—'}}<small v-if="row.item_snapshot?.nature" class="account-nature">{{natureLabel(row.item_snapshot.nature)}}</small></template></el-table-column>
        <el-table-column prop="amount" label="本次金额" min-width="120"/>
        <el-table-column label="币种" min-width="150"><template #default="{row}">{{row.currency || row.account_snapshot?.currency || '待确认'}}<el-button v-if="['payment','opening'].includes(row.entry_type)" link type="primary" :disabled="busy||disabled" @click="openCurrency(row)">核对币种</el-button></template></el-table-column>
        <el-table-column label="付款性质" min-width="185"><template #default="{row}"><strong>{{ classificationLabel(row) }}</strong><small v-if="row.entry_type==='application'" class="account-nature">沿用原定金性质；抵扣非现金付款</small><small v-else v-for="allocation in (row.classification?.allocations||[])" :key="allocation.nature" class="account-nature">{{allocation.nature==='corporate'?'正报':'对私'}} {{allocation.amount}}</small><el-button v-if="['payment','opening'].includes(row.entry_type)" link type="primary" :disabled="busy||disabled" @click="openClassification(row)">{{editable&&row.classification?.can_edit?'核对 / 补充分类':'查看分类'}}</el-button></template></el-table-column>
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
            <template v-for="v in (row.attachments||[])" :key="v.id"><el-button link @click="preview(row,v)">{{v.file_name}} · 预览</el-button><el-button link @click="download(row,v)">下载</el-button></template>
            <span v-if="!row.attachments?.length" class="hint">待上传凭证</span>
            <label v-if="editable && !row.is_reversal && !row.reversed" class="upload-label">上传凭证<input type="file" accept=".pdf,.jpg,.jpeg,.png" :disabled="busy||disabled" @change="upload(row,$event)"/></label>
          </template><span v-else-if="row.entry_type==='application'">沿用原定金凭证<template v-for="v in (row.attachments||[])" :key="v.id"><el-button link @click="preview(row,v)">{{v.file_name}} · 预览</el-button><el-button link @click="download(row,v)">下载</el-button></template></span>
        </template></el-table-column>
        <el-table-column v-if="editable" label="更正" width="110"><template #default="{row}"><router-link v-if="row.payment_batch_href" :to="row.payment_batch_href">批量付款详情</router-link><el-button v-if="!row.payment_batch_id && row.entry_type!=='opening' && !row.reversed && !row.is_reversal && !(kind==='purchase' && row.entry_type==='application')" link type="danger" :disabled="busy||disabled" @click="reverse(row)">{{row.entry_type==='application'?'撤销抵扣':'冲销付款'}}</el-button></template></el-table-column>
      </el-table><el-pagination v-if="filteredEntries.length>20" v-model:current-page="historyPage" :total="filteredEntries.length" :page-size="20" layout="total,prev,pager,next"/>
      </details>
    </template>
    <PaymentCurrencyV2 v-if="currencyTarget" :kind="kind" :id="id" :entry-type="currencyTarget.type" :entry-id="currencyTarget.id" :record-label="currencyTarget.label" @closed="currencyTarget=null" @updated="load();emit('updated')"/>
    <PaymentClassificationV2 v-if="classificationTarget" :kind="kind" :id="id" :entry-type="classificationTarget.type" :entry-id="classificationTarget.id" :record-label="classificationTarget.label" :business-date="classificationTarget.date" @closed="classificationTarget=null" @updated="load();emit('updated')"/>
    <el-dialog v-model="voucherPreviewOpen" title="付款凭证" width="min(1000px,95vw)" @closed="clearVoucherPreview"><el-image v-if="voucherPreviewType.startsWith('image/')" :src="voucherPreviewUrl" :preview-src-list="[voucherPreviewUrl]" fit="contain" style="max-width:100%;max-height:75vh;display:block;margin:auto;cursor:zoom-in"/><div v-else-if="voucherPreviewUrl"><a :href="voucherPreviewUrl" target="_blank" rel="noopener noreferrer">打开 PDF 凭证</a></div></el-dialog>
  </section>
</template>
<script setup>
import {cockpitActorKey} from '../../utils/cockpitDraft';
import PaymentRequestsV2 from './PaymentRequestsV2.vue';
import PaymentTermsPanelV2 from './PaymentTermsPanelV2.vue';
import PaymentPlansPanelV2 from './PaymentPlansPanelV2.vue';
import PaymentCurrencyV2 from './PaymentCurrencyV2.vue';
import PaymentClassificationV2 from './PaymentClassificationV2.vue';
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
const currencyTarget=ref(null);
function openCurrency(row){currencyTarget.value={type:row.entry_type,label:row.reference_number||`记录 ${row.id}`,id:row.entry_type==='opening'?Number(String(row.id).replace(/^opening-/,'')):row.id};}
const classificationTarget=ref(null),classificationFilter=ref('all');
const classificationNature=row=>row.classification?.nature||row.account_snapshot?.nature||'unclassified';
const classificationLabel=row=>({corporate:'对公（正报）',personal:'对私',mixed:'对公与对私',unclassified:'待确认'})[classificationNature(row)]||'待确认';
const filteredEntries=computed(()=>(data.value?.entries||[]).filter(row=>classificationFilter.value==='all'||(classificationNature(row)===classificationFilter.value&&(classificationFilter.value!=='unclassified'||(!row.reversed&&!row.is_reversal&&row.entry_type!=='application')))));
function openClassification(row){classificationTarget.value={type:row.entry_type,label:row.reference_number||`记录 ${row.id}`,date:row.date,id:row.entry_type==='opening'?Number(String(row.id).replace(/^opening-/,'')):row.id};}
watch(()=>[props.kind,props.id,cockpitActorKey(auth.currentUser),auth.authorizationStale],()=>{currencyTarget.value=null;classificationTarget.value=null;classificationFilter.value='all';},{flush:'sync'});
watch(()=>filteredEntries.value.length,()=>{historyPage.value=Math.min(historyPage.value,Math.max(1,Math.ceil(filteredEntries.value.length/20)));});
const today=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const form=reactive({amount:'',currency:'',date:today(),payee_account_id:null,fee_item_id:null,notes:''}),application=reactive({payment_id:null,amount:'',date:today(),cross_order:false,target_purchase_order_id:null});
const applicationPrepayments=computed(()=>application.cross_order?(data.value?.cross_prepayments||[]):(data.value?.available_prepayments||[]));
const crossTargets=computed(()=>{const source=applicationPrepayments.value.find(p=>p.id===application.payment_id);return (data.value?.cross_targets||[]).filter(p=>p.purchase_order_id!==source?.purchase_order_id);});
let generation=0,documentGeneration=0,accountGeneration=0,accountsLoaded=false,attempt=null,uploadAttempt=null,previewGeneration=0;
const voucherPreviewOpen=ref(false),voucherPreviewUrl=ref(''),voucherPreviewType=ref('');
const display=v=>v==null?'待核对':v;
function unwrap(r){if(!r?.success){const details=r?.data;throw new Error(`${r?.message||'付款数据读取失败'}${details?'：'+JSON.stringify(details):''}`);}return r.data;}
function message(e){const details=e.response?.data?.data;return details?`${e.response?.data?.message||e.message}：${JSON.stringify(details)}`:e.message;}
async function load(){const token=++generation,kind=props.kind,id=props.id;loading.value=true;error.value='';try{const result=unwrap(await api.fetchPayments(kind,id));if(!result?.summary)throw new Error('付款接口未返回汇总信息，请确认后端版本');if(token===generation){data.value=result;if(!form.currency)form.currency=result.currency||'';}}catch(e){if(token===generation)error.value=message(e);}finally{if(token===generation)loading.value=false;}}
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
async function save(){try{if(!data.value)throw new Error('请先读取付款信息');const amount=positive(form.amount);if(!form.date)throw new Error('请选择付款日期');if(!form.payee_account_id)throw new Error('请选择收款账户');if(['batch','inbound'].includes(props.kind)&&data.value.itemized&&!form.fee_item_id)throw new Error('请选择费用项目');if(!/^[A-Z]{3}$/.test(form.currency))throw new Error('请确认本次付款币种');await mutate('payment',{amount,currency:form.currency,date:form.date,payee_account_id:form.payee_account_id,...(['batch','inbound'].includes(props.kind)&&data.value.itemized?{fee_item_id:form.fee_item_id}:{}),notes:form.notes,expected_version:data.value.version});}catch(e){error.value=message(e);}}
async function apply(){try{const amount=positive(application.amount);if(!application.payment_id||!application.date)throw new Error('请选择定金和抵扣日期');if(application.cross_order&&!application.target_purchase_order_id)throw new Error('请选择本次抵扣归属采购单');await mutate('application',{payment_id:application.payment_id,amount,date:application.date,expected_version:data.value.version,...(application.cross_order?{cross_order:true,target_purchase_order_id:application.target_purchase_order_id}:{})});}catch(e){error.value=message(e);}}
function resetApplicationSource(){application.payment_id=null;application.target_purchase_order_id=null;}
async function upload(row,event){const file=event.target.files?.[0];event.target.value='';if(!file||busy.value||props.disabled||!editable.value)return;const kind=props.kind,id=props.id,token=documentGeneration;const signature=JSON.stringify([kind,id,row.id,file.name,file.size,file.lastModified]);if(uploadAttempt?.signature!==signature)uploadAttempt={signature,key:api.createIdempotencyKey()};busy.value=true;try{unwrap(await api.uploadPaymentVoucher(kind,id,row.id,file,uploadAttempt.key));if(token!==documentGeneration)return;uploadAttempt=null;await load();}catch(e){if(token===documentGeneration)error.value=message(e);}finally{busy.value=false;}}
async function reverse(row){
  if(row.payment_batch_id)return;
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
function clearVoucherPreview(){previewGeneration++;voucherPreviewOpen.value=false;if(voucherPreviewUrl.value)URL.revokeObjectURL(voucherPreviewUrl.value);voucherPreviewUrl.value='';voucherPreviewType.value='';}
async function preview(row,voucher){if(auth.authorizationStale)return;const token=++previewGeneration;try{const result=await api.previewPaymentVoucher(row.source_kind||props.kind,row.source_id||props.id,row.payment_id||row.id,voucher.id);if(token!==previewGeneration)return;if(!result?.success||!result.blob)throw new Error(result?.message||'凭证读取失败或当前账号无查看权限。');const type=voucher.media_type||result.blob.type;if(type==='application/pdf'||['image/png','image/jpeg'].includes(type)){clearVoucherPreview();voucherPreviewUrl.value=URL.createObjectURL(new Blob([result.blob],{type}));voucherPreviewType.value=type;voucherPreviewOpen.value=true;}else throw new Error('凭证格式不支持预览');}catch(e){if(token===previewGeneration)error.value=e.message||'凭证读取失败';}}
watch(()=>[props.kind,props.id],()=>{clearVoucherPreview();generation++;documentGeneration++;accountGeneration++;data.value=null;historyPage.value=1;accounts.value=[];accountsLoaded=false;attempt=null;uploadAttempt=null;Object.assign(form,{amount:'',currency:'',date:today(),payee_account_id:null,fee_item_id:null,notes:''});Object.assign(application,{payment_id:null,amount:'',date:today(),cross_order:false,target_purchase_order_id:null});load();},{immediate:true});
watch(()=>props.refreshVersion,()=>load());
watch(()=>[cockpitActorKey(auth.currentUser),auth.authorizationStale],clearVoucherPreview,{flush:'sync'});
onUnmounted(()=>{generation++;documentGeneration++;accountGeneration++;clearVoucherPreview();});
defineExpose({load,save,apply,reverse,loadAccounts,preview,form,application,data,error,classificationFilter,filteredEntries});
</script>
<style scoped>
.payment-section{margin:14px 0;border:1px solid #dce4ef;border-radius:8px;padding:14px}.payment-section>summary{font-weight:600;cursor:pointer;padding:4px 0}.payment-section[open]>summary{margin-bottom:14px}
.source-links{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}.source-links a{font-size:13px;color:#2563eb}.payment-panel{margin:20px 0;padding:18px;border:1px solid #dce3ed;border-radius:8px}.payment-panel header{display:flex;align-items:center;justify-content:space-between;gap:12px}.payment-panel h3{margin:0 0 12px}.payment-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0}.payment-summary>div{padding:12px;background:#f5f7fb;border-radius:6px}.payment-summary small,.payment-summary strong,.account-nature{display:block}.payment-summary strong{margin-top:8px;font-size:18px;overflow-wrap:anywhere}.payment-form{display:grid;grid-template-columns:1fr 1fr;gap:12px}.payment-form :deep(.el-select),.payment-form :deep(.el-date-editor){width:100%}.hint{color:#64748b;font-size:13px;line-height:1.6}.application{margin:18px 0}.fee-item-balances{padding:10px 14px;background:#f5f7fb;border-radius:6px;margin:12px 0}.fee-item-balances p{margin:5px 0}.payment-history{margin-top:18px}.upload-label{display:inline-block;position:relative;color:#2563eb;margin:6px;cursor:pointer}.upload-label input{position:absolute;inset:0;opacity:0;width:100%;cursor:pointer}@media(max-width:640px){.payment-summary,.payment-form{grid-template-columns:1fr 1fr}.payment-panel{padding:12px}.payment-panel header{align-items:start}}
</style>
