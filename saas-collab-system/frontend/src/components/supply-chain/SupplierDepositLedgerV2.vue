<template>
  <section class="deposit-ledger">
    <header><div><h3>供应商定金</h3><p>按供应商和币种汇总余额。</p></div><div><el-button link type="primary" :loading="loading" @click="load">刷新</el-button><el-button link type="primary" @click="showLedger=true">{{data.can_manage ? "录入 / 查看明细" : "查看明细"}}</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="deposit-grid"><article v-for="g in data.groups||[]" :key="`${g.supplier_id}-${g.currency}`"><strong>{{g.supplier_name}}</strong><span>{{g.currency}}</span><dl><div><dt>累计存入</dt><dd>{{money(g.paid)}}</dd></div><div><dt>已退回</dt><dd>{{money(g.refunded)}}</dd></div><div><dt>已转采购预付款</dt><dd>{{money(g.transferred)}}</dd></div><div><dt>可用余额</dt><dd>{{money(g.balance)}}</dd></div></dl></article><p v-if="!loading && !(data.groups||[]).length" class="empty">暂无供应商定金余额</p></div>
    <el-dialog v-model="showLedger" title="供应商定金台账" width="min(1120px, 95vw)" append-to-body>
    <details v-if="data.can_manage" ref="editor"><summary>登记存入、退款或转采购预付款</summary><el-form label-position="top" class="deposit-form">
      <el-form-item label="操作"><el-radio-group v-model="form.kind"><el-radio-button value="deposit">存入</el-radio-button><el-radio-button value="refund">退款</el-radio-button><el-radio-button value="transfer">转采购预付款</el-radio-button></el-radio-group></el-form-item>
      <el-form-item label="供应商" required><el-select v-model="form.supplier_id" filterable><el-option v-for="s in data.suppliers||[]" :key="s.id" :label="s.name" :value="s.id"/></el-select></el-form-item>
      <el-form-item v-if="form.kind!=='deposit'" label="来源定金记录" required><el-select v-model="form.deposit_id" filterable placeholder="选择可用定金"><el-option v-for="e in deposits" :key="e.id" :value="e.id" :label="`${e.supplier_name} · ${e.currency} ${e.balance} · ${e.reference}`"/></el-select></el-form-item>
      <el-form-item label="币种" required><el-input v-model="form.currency" maxlength="3" placeholder="例如 USD" /></el-form-item><el-form-item label="金额（最多 4 位小数）" required><el-input v-model="form.amount" inputmode="decimal" /></el-form-item>
      <el-form-item label="日期" required><el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="付款凭证号 / 处理参考号" required><el-input v-model="form.reference" maxlength="200" /></el-form-item>
      <el-form-item v-if="form.kind==='transfer'" label="已确认采购单号" required><el-input v-model="form.purchase_order_number" maxlength="80" /></el-form-item><el-form-item label="备注"><el-input v-model="form.notes" maxlength="500" /></el-form-item>
      <el-button type="primary" :loading="saving" @click="save">提交</el-button>
    </el-form></details>
    <h4>定金流水</h4><el-table :data="data.entries||[]" v-loading="loading" border><el-table-column prop="date" label="日期" width="120"/><el-table-column prop="supplier_name" label="供应商" min-width="150"/><el-table-column label="类型" width="130"><template #default="{row}">{{{deposit:"支付定金",refund:"退回定金",transfer:"转采购预付款"}[row.kind]}}</template></el-table-column><el-table-column prop="currency" label="币种" width="85"/><el-table-column prop="amount" label="金额" width="130"/><el-table-column prop="balance" label="余额" width="130"/><el-table-column prop="reference" label="付款凭证号 / 处理参考号" min-width="150"/><el-table-column prop="purchase_order_number" label="关联采购单" min-width="150"/><el-table-column prop="notes" label="备注" min-width="150"/><el-table-column v-if="data.can_manage" label="操作" width="160"><template #default="{row}"><el-button v-if="row.kind==='deposit'" link @click="startAction(row,'refund')">退款</el-button><el-button v-if="row.kind==='deposit'" link @click="startAction(row,'transfer')">转采购预付款</el-button></template></el-table-column></el-table>
    <el-pagination v-if="data.entry_count > 20" v-model:current-page="page" :page-size="20" :total="data.entry_count" layout="total, prev, pager, next" @current-change="load" />
    </el-dialog>
  </section>
</template>
<script setup>
import {reactive,ref,watch} from 'vue';
import {ElMessage} from 'element-plus';
import * as api from '../../api/supplyCostsV2';
const props=defineProps({countryId:[String,Number]});
const data=ref({}),loading=ref(false),saving=ref(false),error=ref('');
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
const form=reactive({kind:'deposit',supplier_id:null,deposit_id:null,currency:'',amount:'',date:today(),reference:'',notes:'',purchase_order_number:''});
const deposits=ref([]);
const page=ref(1),editor=ref(null),showLedger=ref(false);
let pendingRequest;
let loadSequence=0;
function money(v){return Number(v||0).toFixed(4)}
async function load(){const sequence=++loadSequence;loading.value=true;error.value='';try{const r=await api.fetchSupplierDeposits({offset:(page.value-1)*20,...(props.countryId?{country_id:props.countryId}:{})});if(!r?.success)throw Error(r?.message||'加载失败');if(sequence!==loadSequence)return;data.value=r.data||{};deposits.value=data.value.available_deposits||[]}catch(e){if(sequence===loadSequence)error.value=e.message||'供应商定金加载失败'}finally{if(sequence===loadSequence)loading.value=false}}
function startAction(row,kind){form.kind=kind;form.supplier_id=row.supplier_id;form.deposit_id=row.id;form.currency=row.currency;if(editor.value){editor.value.open=true;editor.value.scrollIntoView({block:"nearest"});}}
async function save(){if(!form.supplier_id||!form.currency||!/^\d+(\.\d{1,4})?$/.test(form.amount)||Number(form.amount)<=0||!form.date||!form.reference.trim()||(form.kind!=='deposit'&&!form.deposit_id)||(form.kind==='transfer'&&!form.purchase_order_number.trim())){error.value='请填写完整信息，金额最多 4 位小数。';return}saving.value=true;error.value='';try{const body={...form,currency:form.currency.trim().toUpperCase(),amount:form.amount.trim(),reference:form.reference.trim(),notes:form.notes.trim()};if(form.kind==='deposit')delete body.deposit_id;if(form.kind!=='transfer')delete body.purchase_order_number;const signature=JSON.stringify(body);if(pendingRequest?.signature!==signature)pendingRequest={signature,key:api.createIdempotencyKey()};const r=await api.createSupplierDepositEntry(body,pendingRequest.key);if(!r?.success)throw Error(r?.message||'提交失败');pendingRequest=null;form.amount='';form.reference='';form.notes='';form.deposit_id=null;await load();ElMessage.success('定金流水已登记')}catch(e){error.value=e.message||'登记失败'}finally{saving.value=false}}
watch(()=>props.countryId, ()=>{page.value=1;form.supplier_id=null;form.deposit_id=null;load();}, {immediate:true});
</script>
<style scoped>
.deposit-ledger{padding:18px;box-sizing:border-box;min-width:0}.deposit-ledger header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.deposit-ledger header>div:last-child{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.deposit-ledger header>div:last-child .el-button+.el-button{margin-left:0}.deposit-ledger h3{margin:0}.deposit-ledger header p{color:#697586;margin:8px 0 0;line-height:1.6}.deposit-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:16px 0}.deposit-grid article{border:1px solid #e3e8ef;border-radius:8px;padding:14px}.deposit-grid article>span{float:right;color:#697586}.deposit-grid dl{margin:12px 0 0}.deposit-grid dl div{display:flex;justify-content:space-between;padding:4px 0}.deposit-grid dt{color:#697586}.deposit-grid dd{margin:0;font-variant-numeric:tabular-nums}.deposit-form{max-width:800px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}.empty{color:#697586;grid-column:1/-1;margin:0;padding:20px 0;line-height:1.6}@media(max-width:850px){.deposit-ledger{padding:12px}.deposit-grid{grid-template-columns:minmax(0,1fr)}}
</style>
