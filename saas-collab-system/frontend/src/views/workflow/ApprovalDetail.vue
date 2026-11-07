<template>
  <section class="approval-detail" v-loading="loading">
    <header class="page-head"><div><h1>审批详情</h1><p>核对申请内容，填写真实审批意见后处理。</p></div><el-tag :type="statusType(detail.status)">{{ statusNames[detail.status] || (detail.status ? '其他状态' : '加载中') }}</el-tag></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-card shadow="never"><template #header>申请信息</template><el-descriptions :column="2" border>
      <el-descriptions-item label="审批类型">{{ detail.approval_type_label || feishuLabels[detail.approval_type] || '其他审批类型' }}</el-descriptions-item><el-descriptions-item label="审批主题">{{ detail.title || '—' }}</el-descriptions-item>
      <el-descriptions-item label="业务类型">{{ detail.business_type_label || '其他业务' }}</el-descriptions-item><el-descriptions-item label="业务单号"><el-button v-if="detail.business_link && detail.business_reference" link type="primary" @click="openSourcePreview">{{ detail.business_reference }}</el-button><span v-else>{{ detail.business_reference || '—' }}</span></el-descriptions-item>
      <el-descriptions-item v-if="detail.payment_display?.application_reference" label="付款申请编号">{{ detail.payment_display.application_reference }}</el-descriptions-item>
      <el-descriptions-item label="申请人">{{ detail.requested_by_name || '姓名未维护' }}</el-descriptions-item><el-descriptions-item label="指定审批人">{{ detail.designated_reviewer_name || '未指定（旧流程）' }}</el-descriptions-item>
      <el-descriptions-item label="实际审批人">{{ detail.reviewed_by_name || '—' }}</el-descriptions-item>
      <el-descriptions-item v-if="detail.workflow_snapshot?.version" label="流程版本">v{{ detail.workflow_snapshot.version }}</el-descriptions-item>
      <el-descriptions-item label="申请时间">{{ formatBeijingTime(detail.created_at) }}</el-descriptions-item><el-descriptions-item label="审批意见">{{ detail.decision_note || '—' }}</el-descriptions-item>
      <template v-if="detail.payment_display">
        <el-descriptions-item label="付款类型">{{ detail.payment_display.payment_type }}</el-descriptions-item>
        <el-descriptions-item label="付款对象">{{ detail.payment_display.payment_object || '—' }}</el-descriptions-item>
        <el-descriptions-item label="申请金额">{{ detail.payment_display.amount }}</el-descriptions-item>
        <el-descriptions-item label="账户性质">{{ detail.payment_display.nature }}</el-descriptions-item>
        <el-descriptions-item label="收款账户尾号">{{ detail.payment_display.account_tail || '—' }}</el-descriptions-item>
        <el-descriptions-item label="申请理由" :span="2">{{ detail.payment_display.reason || '—' }}</el-descriptions-item>
      </template>
      <el-descriptions-item v-else label="申请理由" :span="2">{{ detail.reason || '—' }}</el-descriptions-item>
    </el-descriptions><div v-if="detail.business_link" class="source-actions"><el-button link type="primary" @click="openSourcePreview">预览来源单据</el-button><router-link :to="detail.business_link">打开完整单据</router-link></div></el-card>
    <el-dialog v-model="sourcePreviewOpen" title="来源单据预览" width="min(760px, 94vw)" destroy-on-close>
      <div v-loading="sourcePreviewLoading">
        <el-alert v-if="sourcePreviewError" :title="sourcePreviewError" type="error" show-icon :closable="false" />
        <template v-else-if="sourceDocument">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="单据编号">{{ sourceDocument.target?.number || detail.business_reference || '—' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ sourceDocument.target?.stage || '—' }}</el-descriptions-item>
            <el-descriptions-item label="申请金额">{{ detail.payment_display?.amount || '—' }}</el-descriptions-item>
            <el-descriptions-item label="付款对象">{{ detail.payment_display?.payment_object || '—' }}</el-descriptions-item>
            <el-descriptions-item label="付款类型">{{ detail.payment_display?.payment_type || '—' }}</el-descriptions-item>
            <el-descriptions-item label="申请理由" :span="2">{{ detail.payment_display?.reason || '—' }}</el-descriptions-item>
          </el-descriptions>
          <el-table v-if="sourceDocument.measurements?.length" :data="sourceDocument.measurements" size="small" class="preview-lines">
            <el-table-column prop="product_name" label="商品" min-width="150" />
            <el-table-column prop="sku" label="SKU" min-width="120" />
            <el-table-column prop="quantity" label="数量" width="90" />
          </el-table>
          <p v-else class="preview-empty">商品明细未提供</p>
        </template>
      </div>
      <template #footer><router-link :to="detail.business_link">打开完整单据</router-link><el-button @click="sourcePreviewOpen = false">关闭</el-button></template>
    </el-dialog>
    <el-card v-if="detail.payment_context" shadow="never"><template #header>转账凭证与入账</template>
      <p>审批通过代表已核实实际转账，将自动生成付款记录并计入已付。</p>
      <p>本次金额：{{ detail.payment_context.amount }} · 收款方：{{ detail.payment_context.account_snapshot?.account_holder || '请核对来源单据' }}</p>
      <div v-for="file in detail.payment_context.vouchers || []" :key="file.id"><el-button link @click="previewEvidence(file)">{{ file.file_name }} · 预览</el-button><el-button link @click="downloadEvidence(file)">下载</el-button></div>
      <p v-if="!detail.payment_context.vouchers?.length">尚未上传转账凭证，上传后才能通过付款审批。</p>
      <label v-if="detail.payment_context.can_upload">上传转账凭证（PDF / JPG / PNG）<input type="file" aria-label="上传转账凭证" accept=".pdf,.jpg,.jpeg,.png" :disabled="saving || uploading" @change="uploadEvidence"/></label>
      <el-form v-if="detail.status === 'pending' && canReview && !isApplicant" label-position="top">
        <el-form-item label="实际付款日期" required><el-date-picker v-model="payment.date" type="date" value-format="YYYY-MM-DD"/></el-form-item>
        <el-form-item label="转账参考单号"><el-input v-model="payment.reference_number" maxlength="200"/></el-form-item>
        <el-form-item label="付款备注"><el-input v-model="payment.notes" maxlength="1000"/></el-form-item>
        <p v-if="!detail.payment_context.can_post">当前账户不具备此付款的财务入账权限，无法通过付款审批。</p>
      </el-form>
    </el-card>
    <el-dialog v-model="voucherPreviewOpen" title="转账凭证" width="min(1000px,95vw)" @closed="clearVoucherPreview"><el-image v-if="voucherPreviewType.startsWith('image/')" :src="voucherPreviewUrl" :preview-src-list="[voucherPreviewUrl]" fit="contain" style="max-width:100%;max-height:75vh;display:block;margin:auto;cursor:zoom-in"/><a v-else-if="voucherPreviewUrl" :href="voucherPreviewUrl" target="_blank" rel="noopener noreferrer">打开 PDF 凭证</a></el-dialog>
    <el-card shadow="never"><template #header>状态与审计时间线</template><el-timeline v-if="detail.audit_events?.length"><el-timeline-item v-for="item in detail.audit_events" :key="item.id || item.created_at" :timestamp="formatBeijingTime(item.created_at)">{{ item.action || '其他操作' }}：{{ item.from_status || '—' }} → {{ item.to_status || '—' }}</el-timeline-item></el-timeline><el-empty v-else description="暂无审计事件" /></el-card>
    <el-card v-if="detail.status === 'pending' && canReview && !isApplicant" shadow="never"><template #header>审批意见</template><el-input v-model="note" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="请填写本次审批的实际意见"/><div class="actions"><el-button type="success" :loading="saving" :disabled="!note.trim() || !paymentReady || uploading" @click="decide('approve')">通过</el-button><el-button type="danger" :loading="saving" :disabled="!note.trim()" @click="decide('reject')">驳回</el-button></div></el-card>
    <el-alert v-if="isApplicant && detail.status === 'pending'" title="申请人不能审批自己的申请。" type="warning" :closable="false" />
    <div class="actions"><el-button v-if="detail.status === 'pending' && isApplicant && auth.hasPermission('workflow.approvals.withdraw')" :loading="saving" @click="withdraw">撤回申请</el-button><el-button v-if="auth.hasPermission('feishu.approval.manage') && detail.id" :loading="notifying" @click="notifyFeishu">通知飞书审批映射</el-button></div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { approveApproval, fetchApproval, rejectApproval, withdrawApproval } from '../../api/workflow';
import { notifyFeishuApproval } from '../../api/feishu';
import { useAuthStore } from '../../stores/auth';
import {cockpitActorKey} from '../../utils/cockpitDraft';
import { feishuLabels } from '../../utils/feishuRule';
import { fetchCostContext } from '../../api/supplyCostsV2';

import * as singlePayments from '../../api/paymentRequestsV2';
import * as batchPayments from '../../api/paymentBatchesV2';
const uploading=ref(false);
const voucherPreviewOpen=ref(false),voucherPreviewUrl=ref(''),voucherPreviewType=ref('');let voucherPreviewGeneration=0;
const payment=reactive({date:'',reference_number:'',notes:''});
const paymentReady=computed(()=>!detail.value.payment_context || (detail.value.payment_context.can_post && detail.value.payment_context.vouchers?.length && payment.date));
async function uploadEvidence(event){const file=event.target.files?.[0]; if(!file)return; const id=String(route.params.id),generation=routeGeneration,p={...detail.value.payment_context};uploading.value=true; try{const key=singlePayments.createIdempotencyKey(); const r=p.mode==='batch'?await batchPayments.upload({id:p.batch_id,version:p.version},file,key):await singlePayments.uploadVoucher(p.kind,p.source_id,p.request_id,file,key); if(generation!==routeGeneration||id!==String(route.params.id))return;if(!r?.success)throw new Error(r?.message||'上传失败'); await load();}catch(e){if(generation===routeGeneration&&id===String(route.params.id))ElMessage.error(e.message||'上传失败');}finally{if(generation===routeGeneration)uploading.value=false;event.target.value='';}}
async function downloadEvidence(file){const p=detail.value.payment_context;try{if(p.mode==='batch')await batchPayments.download(p.batch_id,file);else await singlePayments.downloadVoucher(p.kind,p.source_id,p.request_id,file);}catch(e){ElMessage.error(e.message||'下载失败');}}
function clearVoucherPreview(){voucherPreviewGeneration++;if(voucherPreviewUrl.value)URL.revokeObjectURL(voucherPreviewUrl.value);voucherPreviewUrl.value='';voucherPreviewType.value='';}
async function previewEvidence(file){if(auth.authorizationStale)return;const token=++voucherPreviewGeneration,p=detail.value.payment_context;try{const result=p.mode==='batch'?await batchPayments.preview(p.batch_id,file):await singlePayments.previewVoucher(p.kind,p.source_id,p.request_id,file);if(token!==voucherPreviewGeneration)return;if(!result?.success||!result.blob)throw new Error(result?.message||'凭证读取失败或当前账号无查看权限。');const type=file.media_type||result.blob.type;if(!['application/pdf','image/png','image/jpeg'].includes(type))throw new Error('凭证格式不支持预览');clearVoucherPreview();voucherPreviewUrl.value=URL.createObjectURL(new Blob([result.blob],{type}));voucherPreviewType.value=type;voucherPreviewOpen.value=true;}catch(e){if(token===voucherPreviewGeneration)ElMessage.error(e.message||'凭证读取失败');}}
const route = useRoute(); const auth = useAuthStore();
const detail = ref({}); const loading = ref(false); const saving = ref(false); const notifying = ref(false); const error = ref(''); const note = ref('');
const sourcePreviewOpen = ref(false); const sourcePreviewLoading = ref(false); const sourcePreviewError = ref(''); const sourceDocument = ref(null);
let sourcePreviewGeneration = 0; let routeGeneration = 0;
async function openSourcePreview() {
  sourcePreviewOpen.value = true; sourcePreviewLoading.value = true; sourcePreviewError.value = ''; sourceDocument.value = null;
  const routeId = String(route.params.id ?? ''), generation = ++sourcePreviewGeneration;
  const context = detail.value.payment_context;
  try {
    if (!context?.kind || !context?.source_id) throw new Error('来源单据预览信息不可用，可打开完整单据查看。');
    const response = await fetchCostContext(context.kind, context.source_id);
    if (generation !== sourcePreviewGeneration || routeId !== String(route.params.id ?? '') || String(detail.value.id) !== routeId) return;
    if (!response?.success) throw new Error(response?.message || '来源单据加载失败');
    sourceDocument.value = response.data || {};
  } catch (e) { if (generation === sourcePreviewGeneration && routeId === String(route.params.id ?? '')) sourcePreviewError.value = e.message || '来源单据加载失败'; }
  finally { if (generation === sourcePreviewGeneration && routeId === String(route.params.id ?? '')) sourcePreviewLoading.value = false; }
}
const currentUserId = computed(() => String(auth.currentUser?.id ?? auth.currentUser?.user_id ?? ''));
const isApplicant = computed(() => Boolean(currentUserId.value) && currentUserId.value === String(detail.value.requested_by_id ?? detail.value.requested_by?.id ?? ''));
const canReview = computed(() => auth.hasPermission('workflow.approvals.review'));
const statusNames = { pending: '待审批', approved: '已通过', rejected: '已驳回', withdrawn: '已撤回' };
const statusType = (status) => ({ approved: 'success', rejected: 'danger', pending: 'warning', withdrawn: 'info' }[status] || 'info');
function formatBeijingTime(value) {
  if (!value) return '—';
  const parts = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(value));
  const p = Object.fromEntries(parts.map(({type, value: part}) => [type, part]));
  return p.year + '-' + p.month + '-' + p.day + ' ' + p.hour + ':' + p.minute;
}
async function load() { const id = route.params.id, generation = routeGeneration; if (id == null || id === '') { loading.value = false; return; } loading.value = true; error.value = ''; const response = await fetchApproval(id); if (generation !== routeGeneration || String(route.params.id) !== String(id)) return; if (response?.success) detail.value = response.data || {}; else error.value = response?.message || '审批详情加载失败'; loading.value = false; }
async function decide(action) { if (!canReview.value || isApplicant.value || detail.value.status !== 'pending' || !note.value.trim() || uploading.value || (action === 'approve' && !paymentReady.value)) return; const id = detail.value.id, routeId = String(route.params.id), decisionGeneration = routeGeneration, context = detail.value.payment_context ? { ...detail.value.payment_context } : null, decisionNote = note.value.trim(), paymentSnapshot = { ...payment }; try { await ElMessageBox.confirm(`确认${action === 'approve' ? '通过' : '驳回'}此申请？审批意见将记录为审计信息。${action === 'approve' && context ? '通过后将按所填付款日期自动入账，请确认实际转账和凭证无误。' : ''}`, '确认审批', { type: action === 'approve' ? 'success' : 'warning' }); } catch (_error) { return; } if (decisionGeneration !== routeGeneration || routeId !== String(route.params.id) || String(detail.value.id) !== routeId) return; saving.value = true; const response = action === 'approve' ? await approveApproval(id, { note: decisionNote, ...(context ? {payment:{...paymentSnapshot,expected_version:context.version}} : {}) }) : await rejectApproval(id, { note: decisionNote }); if (decisionGeneration !== routeGeneration || routeId !== String(route.params.id) || String(detail.value.id) !== routeId) return; if (response?.success) { ElMessage.success(action === 'approve' ? '审批已通过' : '申请已驳回'); note.value = ''; await load(); } else ElMessage.error(response?.message || '审批操作失败'); saving.value = false; }
async function withdraw() { const id = detail.value.id, routeId = String(route.params.id), generation = routeGeneration; try { await ElMessageBox.confirm('确认撤回此申请？', '撤回确认', { type: 'warning' }); } catch (_error) { return; } if (generation !== routeGeneration || routeId !== String(route.params.id) || String(detail.value.id) !== routeId) return; saving.value = true; const response = await withdrawApproval(id, { note: '申请人撤回申请' }); if (generation !== routeGeneration || routeId !== String(route.params.id) || String(detail.value.id) !== routeId) return; if (response?.success) { ElMessage.success('申请已撤回'); await load(); } else ElMessage.error(response?.message || '撤回失败'); saving.value = false; }
async function notifyFeishu() { const id = detail.value.id, routeId = String(route.params.id), generation = routeGeneration; try { await ElMessageBox.confirm('将按已配置的审批映射通知飞书接收人，继续吗？这不会创建飞书原生审批。', '通知确认', { type: 'warning' }); } catch (_error) { return; } if (generation !== routeGeneration || routeId !== String(route.params.id) || String(detail.value.id) !== routeId) return; notifying.value = true; const response = await notifyFeishuApproval(id); if (generation !== routeGeneration || routeId !== String(route.params.id) || String(detail.value.id) !== routeId) return; if (response?.success) ElMessage.success(response.data?.status === 'no_matching_rule' ? '没有匹配的已启用规则或具备权限的接收人，未发送消息' : '通知已入队，可在飞书协同的运行与事件查看结果'); else ElMessage.error(response?.message || '飞书通知失败'); notifying.value = false; }
watch(() => [route.params.id,cockpitActorKey(auth.currentUser),auth.authorizationStale], () => { routeGeneration++; sourcePreviewGeneration++; clearVoucherPreview(); sourcePreviewOpen.value = false; sourcePreviewLoading.value = false; sourcePreviewError.value = ''; sourceDocument.value = null; detail.value = {}; note.value = ''; payment.date = ''; payment.reference_number = ''; payment.notes = ''; saving.value = false; notifying.value = false; uploading.value = false; loading.value = false; if(!auth.authorizationStale)load(); }, { flush: 'sync' });
onMounted(load);
onUnmounted(clearVoucherPreview);
</script>

<style scoped>
.approval-detail { display: grid; gap: 16px; }.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }.page-head h1 { margin: 0; font-size: 24px; color: #172033; }.page-head p { margin: 7px 0 0; color: #64748b; font-size: 13px; }.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 14px; }
@media (max-width: 640px) { .page-head { align-items: center; }.approval-detail :deep(.el-descriptions__table) { table-layout: fixed; }.approval-detail :deep(.el-descriptions__label), .approval-detail :deep(.el-descriptions__content) { overflow-wrap: anywhere; padding: 8px; } }
</style>
