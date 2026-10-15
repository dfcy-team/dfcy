<template>
  <section class="order-notification" aria-label="订单通知详情">
    <header class="top"><div><h3>订单通知 {{ notice?.order_number || `#${orderId}` }}</h3><p>下单后由后台自动处理；本页只准备、核对或记录结果，不提供单笔手动发送。</p></div><el-button :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="auth.authorizationStale" type="warning" :closable="false" title="权限信息已过期，当前禁止所有写操作。" />
    <el-skeleton v-if="loading && !loaded" :rows="5" animated />
    <template v-else-if="notice">
      <div class="state-row"><el-tag :type="tagType(notice.status)">{{ statusLabel(notice.status) }}</el-tag><span v-if="notice.blocked_message">{{ notice.blocked_message }}</span><span v-else-if="notice.blocked_reason">{{ notice.blocked_reason }}</span></div>
      <div class="summary-grid"><div><small>供应商</small><b>{{ notice.supplier_name || '—' }}</b></div><div><small>订单数量</small><b>{{ notice.total_quantity ?? '—' }}</b></div><div><small>订单金额</small><b>{{ money(notice.total_amount) }}</b></div><div><small>目标</small><b>{{ targetText(notice.target_snapshot) }}</b></div></div>
      <article class="message"><h4>通知正文</h4><pre>{{ notice.summary || '暂无通知正文' }}</pre><div v-if="notice.supplier_url" class="url-row"><a :href="notice.supplier_url" target="_blank" rel="noopener noreferrer">打开实际供应商订单链接</a><el-button size="small" @click="copyLink">复制链接</el-button></div></article>
      <div class="toolbar">
        <el-button v-if="notice.status === 'blocked' && canManage" :disabled="busy" :loading="busyAction === 'prepare'" @click="act('prepare')">准备本地文件</el-button>
        <el-button v-if="canNotify" :disabled="busy || loading || hasAnyAttempt" :loading="busyAction === 'retarget'" @click="openReason('retarget')">刷新目标绑定</el-button>
        <el-button v-if="canNotify" :disabled="busy" :loading="busyAction === 'reconcile'" @click="act('reconcile')">核对工具执行结果</el-button>
        <span class="hint">准备只生成本地文件；核对只查询状态。所有写操作都不会在本页直接发送消息。</span>
      </div>
      <div class="parts"><h4>通知内容部件</h4><article v-for="part in notice.parts || []" :key="part.id" class="part">
        <div class="part-head"><div><b>{{ partLabel(part.kind) }}</b><el-tag size="small" :type="tagType(part.status)">{{ partStatusLabel(part.status) }}</el-tag></div><small>{{ part.object_name || part.text || '' }}</small></div>
        <div v-if="part.kind === 'summary'" class="part-text">{{ part.text }}</div>
        <div v-if="['excel','pdf'].includes(part.kind)" class="file-row"><span>{{ part.object_name || part.kind }} · {{ part.size ? `${Math.ceil(part.size / 1024)} KB` : '文件' }}<template v-if="part.sha256"> · SHA256 {{ part.sha256 }}</template></span><el-button size="small" :disabled="busy" @click="download(part)">下载{{ part.kind.toUpperCase() }}</el-button></div>
        <div v-if="part.kind === 'link' && notice.supplier_url" class="url-row"><a :href="notice.supplier_url" target="_blank" rel="noopener noreferrer">打开供应商订单链接</a><el-button size="small" @click="copy(notice.supplier_url)">复制链接</el-button></div>
        <p v-if="part.attempts?.length" class="attempts">尝试记录：<span v-for="attempt in part.attempts" :key="attempt.id">#{{ attempt.number }} {{ attemptOutcome(attempt.outcome) }}<template v-if="attempt.error_code">（{{ attempt.error_code }}）</template> · {{ date(attempt.finished_at || attempt.started_at) }}；</span></p>
        <p v-if="part.evidence?.length" class="attempts">核验证据：<span v-for="(item,i) in part.evidence" :key="i">{{ item.result === 'delivered' ? '群内已核实' : '确认未送达' }}：{{ item.evidence }} · {{ date(item.created_at) }}；</span></p>
        <el-button v-if="part.status === 'failed' && canNotify" size="small" type="warning" :disabled="busy" @click="openReason('retry', part)">重试已核实失败部件</el-button>
        <el-button v-if="['accepted','executed','unknown','awaiting_execution','awaiting_verification'].includes(part.status) && canNotify" size="small" @click="openVerify(part)">记录实际群核验</el-button>
        <p v-if="['unknown','awaiting_execution'].includes(part.status)" class="unknown">结果未知：请先核对原群并查询工具执行状态，禁止直接重试。</p>
      </article></div>
    </template>
    <el-empty v-else-if="loaded" description="当前订单暂无通知记录；下单后由后台自动处理。" />
    <p v-if="error" class="error">{{ error }}</p>

    <el-dialog v-model="reasonDialog" :title="reasonMode === 'retry' ? '重试失败部件' : '刷新目标绑定'" width="min(520px, 94vw)">
      <p v-if="reasonMode === 'retry'">仅重试当前失败部件；已送达部件不会重发。结果未知的部件需先核对原群。</p>
      <el-input v-model="reason" type="textarea" :rows="3" maxlength="500" placeholder="填写原因" :disabled="busy" />
      <template #footer><el-button @click="reasonDialog=false">取消</el-button><el-button type="primary" :disabled="busy || !reason.trim()" :loading="busy" @click="submitReason">确认</el-button></template>
    </el-dialog>
    <el-dialog v-model="verifyDialog" title="记录实际群核验" width="min(560px, 94vw)">
      <el-radio-group v-model="verifyResult" :disabled="busy"><el-radio value="delivered">已在群内核实送达</el-radio><el-radio value="not_delivered">已确认未送达</el-radio></el-radio-group>
      <el-input v-model="verifyEvidence" type="textarea" :rows="3" maxlength="1000" placeholder="描述群内证据、核验人和时间" :disabled="busy" />
      <el-checkbox v-if="verifyResult === 'not_delivered' && ['accepted','executed','unknown','awaiting_execution','awaiting_verification'].includes(verifyPart?.status)" v-model="executionStopped" :disabled="busy">我已确认工具停止执行</el-checkbox>
      <template #footer><el-button @click="verifyDialog=false">取消</el-button><el-button type="primary" :disabled="busy || !verifyEvidence.trim() || (verifyResult === 'not_delivered' && ['accepted','executed','unknown','awaiting_execution','awaiting_verification'].includes(verifyPart?.status) && !executionStopped)" :loading="busy" @click="submitVerify">保存核验</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { downloadSupplyNotificationPart, fetchPurchaseOrderNotification, fetchSupplyNotification, prepareSupplyNotification, reconcileSupplyNotification, retargetSupplyNotification, retrySupplyNotificationPart, verifySupplyNotificationPart } from '../../api/supplyNotificationsV2';

const props = defineProps({ orderId: { type: [String, Number], required: true }, version: { type: [String, Number], default: null } });
const auth = useAuthStore(); const canManage = computed(() => auth.hasPermission('supply.v2.manage') && !auth.authorizationStale); const canNotify = computed(() => canManage.value && auth.hasPermission('supply.v2.notify'));
const notice = ref(null); const loading = ref(false); const loaded = ref(false); const busy = ref(false); const busyAction = ref(''); const error = ref(''); const dirty = ref(false);
const reasonDialog = ref(false); const reasonMode = ref(''); const reason = ref(''); const selectedPart = ref(null); const verifyDialog = ref(false); const verifyPart = ref(null); const verifyResult = ref('delivered'); const verifyEvidence = ref(''); const executionStopped = ref(false);
const hasAnyAttempt = computed(() => (notice.value?.parts || []).some((part) => part.attempts?.length));
const labels = { blocked:'待配置/需处理', queued:'待发送', sending:'发送中', awaiting_execution:'接口已受理', awaiting_verification:'工具已执行待核实', delivered:'群内已核实', failed:'失败', unknown:'结果未知', offline:'发送端离线' };
const partLabels = { pending:'待发送', sending:'发送中', accepted:'接口已受理', executed:'工具执行成功', delivered:'群内已核实', failed:'失败', unknown:'结果未知' };
function statusLabel(s){ return labels[s] || s || '—'; } function partStatusLabel(s){ return partLabels[s] || statusLabel(s); }
function tagType(s){ return ['delivered','online'].includes(s)?'success':['failed','offline','unknown','blocked'].includes(s)?'danger':['sending','queued','accepted','executed','awaiting_execution','awaiting_verification'].includes(s)?'warning':'info'; }
function partLabel(k){ return ({summary:'通知正文',excel:'Excel 订单文件',pdf:'PDF 订单文件',link:'订单链接'})[k] || k; }
function attemptOutcome(o){ return ({delivered:'群内已核实',accepted:'接口已受理',executed:'工具执行成功',failed:'失败',unknown:'结果未知'})[o] || o || '处理中'; }
function targetText(t){ return [t?.channel_name,t?.sender_name,t?.device_name,t?.group_name].filter(Boolean).join(' · ') || '—'; }
function money(v){ return v == null ? '—' : new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'}).format(Number(v)); }
function date(v){ return v ? new Date(v).toLocaleString('zh-CN') : '时间未知'; }
async function load(force=false){ if(dirty.value&&!force)return; loading.value=true; error.value=''; try { const response=await fetchPurchaseOrderNotification(props.orderId); if(!response?.success) throw new Error(response?.message||'读取通知失败'); let item=response.data||null; if(item?.id){ const detail=await fetchSupplyNotification(item.id); if(detail?.success) item=detail.data; } notice.value=item; loaded.value=true; dirty.value=false; } catch(e){ error.value=e?.message||'读取通知失败'; } finally { loading.value=false; } }
async function act(action){ if(busy.value)return; busy.value=true;busyAction.value=action;error.value=''; try { const id=notice.value?.id; const response=action==='prepare'?await prepareSupplyNotification(id,{expected_version:notice.value.version}):action==='retarget'?await retargetSupplyNotification(id,{expected_version:notice.value.version,reason:reason.value.trim()}):await reconcileSupplyNotification(id,{expected_version:notice.value.version}); if(!response?.success)throw new Error(response?.message||'操作失败'); reasonDialog.value=false; reason.value=''; await load(true); } catch(e){error.value=e?.message||'操作失败；若网络结果未知，请刷新核对状态。'}finally{busy.value=false;busyAction.value='';} }
function openReason(mode,part=null){reasonMode.value=mode;selectedPart.value=part;reason.value='';reasonDialog.value=true;}
async function submitReason(){if(!reason.value.trim())return;if(reasonMode.value==='retarget'){await act('retarget');return;}if(busy.value)return;busy.value=true;error.value='';try{const p=selectedPart.value;const response=await retrySupplyNotificationPart(notice.value.id,p.id,{expected_version:p.version,reason:reason.value.trim()});if(!response?.success)throw new Error(response?.message||'重试操作失败');reasonDialog.value=false;await load(true);}catch(e){error.value=e?.message||'重试结果未知，请刷新核对状态。'}finally{busy.value=false;}}
function openVerify(part){verifyPart.value=part;verifyResult.value='delivered';verifyEvidence.value='';executionStopped.value=false;verifyDialog.value=true;}
async function submitVerify(){if(busy.value||!verifyEvidence.value.trim())return;busy.value=true;error.value='';try{const p=verifyPart.value;const response=await verifySupplyNotificationPart(notice.value.id,p.id,{expected_version:p.version,result:verifyResult.value,evidence:verifyEvidence.value.trim(),execution_stopped:executionStopped.value});if(!response?.success)throw new Error(response?.message||'保存核验失败');verifyDialog.value=false;await load(true);}catch(e){error.value=e?.message||'核验结果未知，请刷新确认。'}finally{busy.value=false;}}
async function download(part){try{const r=await downloadSupplyNotificationPart(notice.value.id,part.id,part.object_name||`${notice.value.order_number}.${part.kind==='excel'?'xlsx':'pdf'}`);if(!r?.success)throw new Error(r?.message||'下载失败');}catch(e){error.value=e?.message||'下载失败';}}
async function copy(value){try{await navigator.clipboard.writeText(value);}catch{error.value='无法访问剪贴板，请手动复制链接。'}} async function copyLink(){await copy(notice.value?.supplier_url||'');}
watch([reason,verifyEvidence,executionStopped],()=>{if(reasonDialog.value||verifyDialog.value)dirty.value=true;});
watch(()=>props.orderId,()=>{dirty.value=false;load(true);});watch(()=>props.version,()=>{if(loaded.value&&!dirty.value)load(true);});onMounted(()=>load(true));
</script>

<style scoped>
.order-notification{min-width:0}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.top h3{margin:0 0 5px}.top p,.hint,.attempts{color:#657184;font-size:13px}.state-row{display:flex;align-items:center;gap:10px;margin:12px 0}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}.summary-grid div,.message,.part{border:1px solid #dce3ed;border-radius:9px;padding:12px;min-width:0}.summary-grid small,.summary-grid b{display:block}.summary-grid small{color:#657184;margin-bottom:5px}.summary-grid b{overflow-wrap:anywhere}.message h4,.parts h4{margin:0 0 8px}.message pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:0}.url-row,.file-row,.part-head,.part-head>div{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.url-row{margin-top:10px}.url-row a{overflow-wrap:anywhere}.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0}.hint{flex-basis:100%}.parts{margin-top:16px}.part{margin:10px 0}.part-head{justify-content:space-between}.part-head small{overflow-wrap:anywhere;color:#657184}.part-text{white-space:pre-wrap;overflow-wrap:anywhere;margin:10px 0}.file-row{justify-content:space-between;margin:10px 0}.attempts{overflow-wrap:anywhere}.unknown{color:#a35b00;background:#fff8e8;padding:9px;border-radius:7px}.error{color:#c0392b}@media(max-width:650px){.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.top{align-items:flex-start}.order-notification{overflow-wrap:anywhere}}
</style>
