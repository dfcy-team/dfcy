<template>
  <section class="approval-detail" v-loading="loading">
    <header class="page-head"><div><h1>审批详情</h1><p>核对申请内容，填写真实审批意见后处理。</p></div><el-tag :type="statusType(detail.status)">{{ statusNames[detail.status] || detail.status || '加载中' }}</el-tag></header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-card shadow="never"><template #header>申请信息</template><el-descriptions :column="2" border>
      <el-descriptions-item label="审批类型">{{ feishuLabels[detail.approval_type] || detail.approval_type || '—' }}</el-descriptions-item><el-descriptions-item label="审批主题">{{ detail.title || '—' }}</el-descriptions-item>
      <el-descriptions-item label="业务类型">{{ detail.business_type || '—' }}</el-descriptions-item><el-descriptions-item label="业务 ID">{{ detail.business_id || '—' }}</el-descriptions-item>
      <el-descriptions-item label="申请人">{{ detail.requested_by_name || detail.requested_by_id || '—' }}</el-descriptions-item><el-descriptions-item label="审批人">{{ detail.reviewed_by_name || detail.reviewed_by_id || '—' }}</el-descriptions-item>
      <el-descriptions-item label="申请时间">{{ detail.created_at || '—' }}</el-descriptions-item><el-descriptions-item label="审批意见">{{ detail.decision_note || '—' }}</el-descriptions-item>
      <el-descriptions-item label="申请理由" :span="2">{{ detail.reason || '—' }}</el-descriptions-item>
    </el-descriptions></el-card>
    <el-card shadow="never"><template #header>状态与审计时间线</template><el-timeline v-if="detail.audit_events?.length"><el-timeline-item v-for="item in detail.audit_events" :key="item.id || item.created_at" :timestamp="item.created_at">{{ item.action }}：{{ item.from_status || '—' }} → {{ item.to_status || '—' }}</el-timeline-item></el-timeline><el-empty v-else description="暂无审计事件" /></el-card>
    <el-card v-if="detail.status === 'pending' && canReview && !isApplicant" shadow="never"><template #header>审批意见</template><el-input v-model="note" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="请填写本次审批的实际意见"/><div class="actions"><el-button type="success" :loading="saving" :disabled="!note.trim()" @click="decide('approve')">通过</el-button><el-button type="danger" :loading="saving" :disabled="!note.trim()" @click="decide('reject')">驳回</el-button></div></el-card>
    <el-alert v-if="isApplicant && detail.status === 'pending'" title="申请人不能审批自己的申请。" type="warning" :closable="false" />
    <div class="actions"><el-button v-if="detail.status === 'pending' && isApplicant && auth.hasPermission('workflow.approvals.withdraw')" :loading="saving" @click="withdraw">撤回申请</el-button><el-button v-if="auth.hasPermission('feishu.approval.manage') && detail.id" :loading="notifying" @click="notifyFeishu">通知飞书审批映射</el-button></div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { approveApproval, fetchApproval, rejectApproval, withdrawApproval } from '../../api/workflow';
import { notifyFeishuApproval } from '../../api/feishu';
import { useAuthStore } from '../../stores/auth';
import { feishuLabels } from '../../utils/feishuRule';

const route = useRoute(); const auth = useAuthStore();
const detail = ref({}); const loading = ref(false); const saving = ref(false); const notifying = ref(false); const error = ref(''); const note = ref('');
const currentUserId = computed(() => String(auth.currentUser?.id ?? auth.currentUser?.user_id ?? ''));
const isApplicant = computed(() => Boolean(currentUserId.value) && currentUserId.value === String(detail.value.requested_by_id ?? detail.value.requested_by?.id ?? ''));
const canReview = computed(() => auth.hasPermission('workflow.approvals.review'));
const statusNames = { pending: '待审批', approved: '已通过', rejected: '已驳回', withdrawn: '已撤回' };
const statusType = (status) => ({ approved: 'success', rejected: 'danger', pending: 'warning', withdrawn: 'info' }[status] || 'info');
async function load() { loading.value = true; error.value = ''; const response = await fetchApproval(route.params.id); if (response?.success) detail.value = response.data || {}; else error.value = response?.message || '审批详情加载失败'; loading.value = false; }
async function decide(action) { if (!canReview.value || isApplicant.value || detail.value.status !== 'pending' || !note.value.trim()) return; try { await ElMessageBox.confirm(`确认${action === 'approve' ? '通过' : '驳回'}此申请？审批意见将记录为审计信息。`, '确认审批', { type: action === 'approve' ? 'success' : 'warning' }); } catch (_error) { return; } saving.value = true; const response = action === 'approve' ? await approveApproval(detail.value.id, { note: note.value.trim() }) : await rejectApproval(detail.value.id, { note: note.value.trim() }); if (response?.success) { ElMessage.success(action === 'approve' ? '审批已通过' : '申请已驳回'); note.value = ''; await load(); } else ElMessage.error(response?.message || '审批操作失败'); saving.value = false; }
async function withdraw() { try { await ElMessageBox.confirm('确认撤回此申请？', '撤回确认', { type: 'warning' }); } catch (_error) { return; } saving.value = true; const response = await withdrawApproval(detail.value.id, { note: '申请人撤回申请' }); if (response?.success) { ElMessage.success('申请已撤回'); await load(); } else ElMessage.error(response?.message || '撤回失败'); saving.value = false; }
async function notifyFeishu() { try { await ElMessageBox.confirm('将按已配置的审批映射通知飞书接收人，继续吗？这不会创建飞书原生审批。', '通知确认', { type: 'warning' }); } catch (_error) { return; } notifying.value = true; const response = await notifyFeishuApproval(detail.value.id); if (response?.success) ElMessage.success(response.data?.status === 'no_matching_rule' ? '没有匹配的已启用规则或具备权限的接收人，未发送消息' : '通知已入队，可在飞书协同的运行与事件查看结果'); else ElMessage.error(response?.message || '飞书通知失败'); notifying.value = false; }
onMounted(load);
</script>

<style scoped>
.approval-detail { display: grid; gap: 16px; }.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }.page-head h1 { margin: 0; font-size: 24px; color: #172033; }.page-head p { margin: 7px 0 0; color: #64748b; font-size: 13px; }.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 14px; }
@media (max-width: 640px) { .page-head { align-items: center; }.approval-detail :deep(.el-descriptions__table) { table-layout: fixed; }.approval-detail :deep(.el-descriptions__label), .approval-detail :deep(.el-descriptions__content) { overflow-wrap: anywhere; padding: 8px; } }
</style>
