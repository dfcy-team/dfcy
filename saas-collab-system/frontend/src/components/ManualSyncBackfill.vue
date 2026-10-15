<template>
  <el-drawer
    :model-value="modelValue"
    title="任务手动补采"
    size="min(640px, 96vw)"
    destroy-on-close
    @close="$emit('update:modelValue', false)"
  >
    <template v-if="job">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="固定任务">#{{ job.id }} · {{ job.subject_name || job.shop_name || '未命名主体' }}</el-descriptions-item>
        <el-descriptions-item label="平台与数据类型">Shopee · {{ resourceLabel(job.resource_type) }}</el-descriptions-item>
      </el-descriptions>
      <p class="notice">补采只读取平台数据并写入本地；任务不会加入常规同步队列。平台可能无法提供所选日期的全部数据。</p>
      <el-alert v-if="createBlockReason" type="warning" :closable="false" :title="createBlockReason" />
      <el-form label-position="top" class="form">
        <div class="dates">
          <el-form-item label="开始日期"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item>
          <el-form-item label="结束日期（含）"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item>
        </div>
        <p v-if="validationMessage" class="error">{{ validationMessage }}</p>
        <el-button type="primary" :loading="busy === 'create' || busy === 'confirm'" :disabled="!canManage || !validForm || !!busy" @click="create">确认补采</el-button>
      </el-form>

      <section v-if="canView" class="legacy" aria-label="该任务的历史补采进度">
        <header><h3>已有补采任务</h3><el-button :loading="loading" :disabled="!canView" @click="load">刷新</el-button></header>
        <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" />
        <el-empty v-else-if="!loading && !batches.length" description="该任务暂无历史补采记录" />
        <article v-for="batch in batches" :key="batch.id" class="batch">
          <div class="batch-heading">
            <div><strong>{{ batch.name || `历史补采 #${batch.id}` }}</strong><small>{{ batch.start_date }} 至 {{ batch.end_date }} · {{ statusText(batch.status) }}</small></div>
            <div v-if="canManage" class="actions">
              <el-button v-if="batch.status === 'running'" size="small" :disabled="!safeBatchControl(batch) || !!busy" :title="batchControlReason(batch)" @click="act(batch, 'pause')">暂停</el-button>
              <el-button v-if="batch.status === 'paused'" size="small" :disabled="!safeBatchControl(batch) || !!busy" :title="batchControlReason(batch)" @click="act(batch, 'resume')">继续</el-button>
              <el-button v-if="batch.failed_segments > 0" size="small" type="warning" :disabled="!safeBatchControl(batch) || !!busy" :title="batchControlReason(batch)" @click="act(batch, 'retry_failed')">重试可恢复失败分段</el-button>
            </div>
          </div>
          <el-progress :percentage="percent(batch.success_segments + batch.failed_segments, batch.total_segments)" :status="batch.failed_segments ? 'exception' : undefined" />
          <small>分段 {{ batch.success_segments || 0 }} 成功 / {{ batch.failed_segments || 0 }} 失败 / {{ batch.total_segments || 0 }} 总计 · 已获取 {{ batch.fetched_count || 0 }} 条</small>
          <div v-for="shop in currentJobShops(batch)" :key="shop.job_id" class="shop">
            <div><strong>{{ resourceLabel(shop.resource_type) }} · {{ statusText(shop.status) }}</strong></div>
            <el-progress :percentage="percent((shop.success_segments || 0) + (shop.failed_segments || 0), shop.total_segments)" :status="shop.failed_segments ? 'exception' : undefined" />
            <small>{{ shop.success_segments || 0 }}/{{ shop.total_segments || 0 }} 分段 · {{ shop.fetched_count || 0 }} 条</small>
            <p v-if="shop.authorization" class="recovery">当前授权：{{ authorizationLabel(shop.authorization) }}<template v-if="shop.authorization.expires_at"> · 到期 {{ shop.authorization.expires_at }}</template></p>
            <p v-if="shop.waiting_for_refresh > 0" class="recovery">等待授权续期：{{ shop.waiting_for_refresh }} 个分段</p>
            <p v-if="shop.recovery_hint" class="recovery">恢复提示：{{ shop.recovery_hint }}</p>
            <p v-if="shop.last_error" class="error">历史运行错误：{{ shop.last_error }}</p>
          </div>
          <p v-if="!safeBatchControl(batch)" class="recovery">{{ batchControlReason(batch) }}</p>
        </article>
      </section>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { actOnHistorySyncBatch, createHistorySyncBatch, fetchHistorySyncBatches } from '../api/integrations';
import { useAuthStore } from '../stores/auth';

const props = defineProps({ modelValue: { type: Boolean, default: false }, job: { type: Object, default: null } });
defineEmits(['update:modelValue']);
const auth = useAuthStore();
const canView = computed(() => auth.hasPermission('integrations.history.view'));
const canManage = computed(() => auth.hasPermission('integrations.history.manage') && auth.hasPermission('integrations.run_live_readonly'));
const form = reactive({ start_date: '', end_date: '' });
const busy = ref(''), loading = ref(false), loadError = ref(''), batches = ref([]);
let submittedRequest = null, requestSequence = 0, timer = null, unmounted = false;
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
const resourceLabels = { sales_order: '销售订单', refund_return: '退货退款', settlement_bill: '财务流水' };
const canOperateJob = computed(() => props.job?.platform === 'shopee'
  && ['sales_order', 'refund_return', 'settlement_bill'].includes(props.job.resource_type)
  && ['pilot', 'production'].includes(props.job.environment)
  && props.job.is_enabled === true
  && ['ready', 'not_required'].includes(props.job.capability_state)
  && !props.job.blocked_reason
  && !['queued', 'running'].includes(props.job.schedule_state)
  && props.job.status !== 'running');
const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const validationMessage = computed(() => {
  const { start_date: start, end_date: end } = form;
  if (!start || !end) return '请选择开始日期和结束日期。';
  if (!validDate(start) || !validDate(end)) return '请输入有效的 YYYY-MM-DD 日历日期。';
  if (start > end) return '开始日期不能晚于结束日期。';
  if (end > today) return '结束日期不能晚于北京时间今天。';
  if ((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000 > 3660) return '开始和结束日期间隔不能超过 3660 天。';
  return '';
});
const validForm = computed(() => !validationMessage.value && !!props.job?.id && canOperateJob.value);
const createBlockReason = computed(() => {
  if (!canManage.value) return '当前账号缺少历史补采管理或真实只读执行权限；仍可查看已有进度。';
  if (!props.job) return '当前任务信息不可用。';
  if (!['sales_order', 'refund_return', 'settlement_bill'].includes(props.job.resource_type)) return '该资源类型不支持历史补采。';
  if (!['pilot', 'production'].includes(props.job.environment) || props.job.platform !== 'shopee') return '仅支持 Shopee 实际任务。';
  if (!props.job.is_enabled || props.job.status === 'disabled') return '任务已停用；启用后才能创建补采，现有进度仍可查看。';
  if (props.job.blocked_reason) return `任务当前受阻：${props.job.blocked_reason}`;
  if (!['ready', 'not_required'].includes(props.job.capability_state)) return '只读能力未就绪；检查能力和授权后才能创建补采。';
  if (['queued', 'running'].includes(props.job.schedule_state) || props.job.status === 'running') return '任务正在排队或运行；请完成当前运行后再创建补采。';
  return '';
});
function resourceLabel(value) { return resourceLabels[value] || value || '未知类型'; }
function disableFutureDate(date) { return date.getTime() > new Date(`${today}T23:59:59+08:00`).getTime(); }
function percent(done, total) { return total ? Math.min(100, Math.round(done * 100 / total)) : 0; }
function statusText(status) { return ({ running: '运行中', queued: '排队中', paused: '已暂停', completed: '已完成', failed: '失败', partial: '部分失败', pending: '待处理' })[status] || status || '未知'; }
function authorizationLabel(state) {
  if (!state) return '状态未知';
  if (state.expired) return '已过期';
  return ({ disabled: '续期未启用', not_due: '尚未到续期时间', manual_recovery: '需人工恢复', refreshing: '正在续期', retry_wait: '等待重试', due: '到期待执行', blocked: '授权受阻' })[state.state] || '状态未知';
}
function currentJobShops(batch) { return (batch.shops || []).filter(shop => String(shop.job_id) === String(props.job?.id)); }
function hasJobShop(batch, jobId) { return (batch?.shops || []).some(shop => String(shop.job_id) === String(jobId)); }
function safeBatchControl(batch) {
  return batch.task_action_allowed === true;
}
function batchControlReason(batch) {
  return safeBatchControl(batch) ? '' : '此历史批次包含其他任务，或接口未能证明其任务范围；为避免影响其他任务，不能在此控制整个批次。';
}
function updateTimer() {
  const active = props.modelValue && batches.value.some(batch => ['running', 'queued'].includes(batch.status));
  if (active && !timer) timer = globalThis.setInterval(load, 10000);
  if (!active && timer) { globalThis.clearInterval(timer); timer = null; }
}
async function load() {
  if (unmounted || !props.modelValue || !props.job?.id || !canView.value) return;
  const sequence = ++requestSequence;
  loading.value = true; loadError.value = '';
  try {
    const result = await fetchHistorySyncBatches({ sync_job_id: props.job.id });
    if (unmounted || !props.modelValue || sequence !== requestSequence) return;
    if (!result?.success) throw new Error(result?.message || '历史补采进度读取失败');
    batches.value = result.data?.batches || [];
  } catch (error) {
    if (unmounted || !props.modelValue || sequence !== requestSequence) return;
    batches.value = []; loadError.value = error?.message || '历史补采进度读取失败';
  } finally {
    if (!unmounted && props.modelValue && sequence === requestSequence) { loading.value = false; updateTimer(); }
  }
}
async function create() {
  if (!canManage.value || !validForm.value || busy.value) return;
  busy.value = 'confirm';
  const job = props.job;
  const start = form.start_date, end = form.end_date;
  try {
    await ElMessageBox.confirm(`将为任务 #${job.id}（${resourceLabel(job.resource_type)}）补采 ${start} 至 ${end}（含）。此操作只读平台并写入本地，不进入常规同步队列。继续？`, '确认任务手动补采', { type: 'warning' });
  } catch { busy.value = ''; return; }
  if (!canManage.value || !canOperateJob.value || !props.modelValue || String(props.job?.id) !== String(job.id)) { busy.value = ''; ElMessage.error('权限、任务状态或当前任务已变化，请重新检查后再提交。'); return; }
  busy.value = 'create';
  const payload = { name: `手动补采任务 #${job.id}`, job_ids: [job.id], start_date: start, end_date: end };
  const signature = JSON.stringify(payload);
  if (!submittedRequest || submittedRequest.signature !== signature) submittedRequest = { signature, key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` };
  try {
    const result = await createHistorySyncBatch({ ...payload, idempotency_key: submittedRequest.key });
    if (!result?.success) throw new Error(result?.message || '历史补采提交失败');
    ElMessage.success('补采任务已提交；请查看当前任务的历史进度。');
    await load();
  } catch (error) { ElMessage.error(error?.message || '历史补采提交失败'); }
  finally { busy.value = ''; }
}
async function act(batch, action) {
  if (!canManage.value || !safeBatchControl(batch) || busy.value) return;
  const jobId = String(props.job?.id || '');
  const batchId = String(batch.id);
  if (!jobId || !hasJobShop(batch, jobId)) return;
  busy.value = `${batch.id}:${action}`;
  try {
    if (action === 'retry_failed') {
      try { await ElMessageBox.confirm(`将重试批次“${batch.name || batch.id}”中可恢复的失败分段。${batch.status === 'paused' ? '批次会保持暂停；如需继续，请单独点击“继续”。' : '本操作不会自动暂停批次。'}继续？`, '确认重试失败分段', { type: 'warning' }); }
      catch { return; }
    }
    if (!canManage.value || !props.modelValue || String(props.job?.id || '') !== jobId) return;
    const currentBatch = batches.value.find(item => String(item.id) === batchId);
    if (!currentBatch || !safeBatchControl(currentBatch) || !hasJobShop(currentBatch, jobId)) return;
    const result = await actOnHistorySyncBatch(currentBatch.id, action);
    if (!result?.success) throw new Error(result?.message || '批次操作失败');
    ElMessage.success('批次操作已提交'); await load();
  } catch (error) { ElMessage.error(error?.message || '批次操作失败'); }
  finally { busy.value = ''; }
}
watch(() => [props.modelValue, props.job?.id], ([open, id]) => {
  requestSequence += 1;
  if (timer) { globalThis.clearInterval(timer); timer = null; }
  if (!open) { loading.value = false; return; }
  batches.value = []; loadError.value = '';
  if (id && canView.value) load();
}, { immediate: true });
watch(canView, allowed => {
  if (allowed && props.modelValue) load();
  else {
    requestSequence += 1;
    batches.value = [];
    loadError.value = '';
    loading.value = false;
    if (timer) { globalThis.clearInterval(timer); timer = null; }
  }
});
onUnmounted(() => { unmounted = true; requestSequence += 1; if (timer) globalThis.clearInterval(timer); timer = null; });
</script>

<style scoped>
.notice,.recovery{color:#475569;font-size:13px;line-height:1.55}.form{margin-top:18px}.dates{display:grid;grid-template-columns:1fr 1fr;gap:12px}.dates :deep(.el-date-editor){width:100%}.legacy{margin-top:28px}.legacy header,.batch-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.legacy h3{font-size:16px}.batch{padding:14px 0;border-bottom:1px solid #e2e8f0}.batch-heading small,.batch small{display:block;color:#64748b;font-size:12px}.actions{display:flex;gap:6px}.shop{margin:12px 0;padding:12px;border:1px solid #e2e8f0;border-radius:8px}.error{color:#b91c1c;font-size:13px}@media(max-width:640px){.dates{grid-template-columns:1fr}.batch-heading{align-items:flex-start;flex-direction:column}}
</style>
