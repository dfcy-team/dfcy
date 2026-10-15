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
      <p class="notice">补采只读取平台数据并写入本地；任务不会加入常规同步队列。平台可能无法提供所选日期的全部数据。普通任务仍按原有日期校验规则处理，不改变日常同步设置。</p>
      <el-alert v-if="createBlockReason" type="warning" :closable="false" :title="createBlockReason" />
      <el-form label-position="top" class="form">
        <div class="dates">
          <el-form-item :label="isAdvertising ? '店铺站点开始日期' : '开始日期'"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item>
          <el-form-item :label="isAdvertising ? '店铺站点结束日期（含）' : '结束日期（含）'"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item>
        </div>
        <template v-if="isAdvertising">
          <el-form-item label="广告报表"><el-select v-model="form.advertising_datasets" multiple collapse-tags collapse-tags-tooltip :disabled="!advertisingAvailable" placeholder="选择要补采的报表"><el-option v-for="item in advertisingDatasets" :key="item.value" :value="item.value" :label="item.label" /></el-select></el-form-item>
          <el-alert v-if="!advertisingAvailable" type="warning" :closable="false" title="当前后端未声明广告补采能力，请升级后再使用。" />
          <el-alert v-if="!shopToday" type="info" :closable="false" title="请按店铺站点日期选择最近 6 个月；当前任务未提供有效站点时区，最终日期范围由后端校验。" />
          <p v-else class="notice">日期按店铺站点时区 {{ shopTimezone }} 计算；最近 6 个月由表单校验。</p>
        </template>
        <template v-if="nightWindowsAvailable">
          <el-form-item label="执行时段">
            <el-radio-group v-model="form.execution_mode"><el-radio-button value="anytime">随时执行</el-radio-button><el-radio-button value="night">夜间窗口</el-radio-button></el-radio-group>
          </el-form-item>
          <div v-if="form.execution_mode === 'night'" class="dates">
            <el-form-item label="北京时间开始"><el-time-picker v-model="form.start_time" value-format="HH:mm" format="HH:mm" /></el-form-item>
            <el-form-item label="北京时间结束"><el-time-picker v-model="form.end_time" value-format="HH:mm" format="HH:mm" /></el-form-item>
          </div>
          <p v-if="scheduleValidation" class="error">{{ scheduleValidation }}</p>
        </template>
        <el-alert v-else-if="featuresLoaded && !nightWindowsAvailable" type="info" :closable="false" title="后端未声明夜间窗口能力；升级后可选择执行时段。" />
        <p v-if="validationMessage" class="error">{{ validationMessage }}</p>
        <el-button type="primary" :loading="busy === 'create' || busy === 'confirm'" :disabled="!canManage || !validForm || !!busy" @click="create">确认补采</el-button>
      </el-form>

      <section v-if="canView" class="legacy" aria-label="该任务的历史补采进度">
        <header><h3>已有补采任务</h3><el-button :loading="loading" :disabled="!canView" @click="load">刷新</el-button></header>
        <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" />
        <el-empty v-else-if="!loading && !batches.length" description="该任务暂无历史补采记录" />
        <article v-for="batch in batches" :key="batch.id" class="batch">
          <div class="batch-heading">
            <div><strong>{{ batch.name || `历史补采 #${batch.id}` }}</strong><small>{{ batch.start_date }} 至 {{ batch.end_date }} · 批次{{ statusText(batch.status) }}</small></div>
            <div v-if="canManage && taskControlsAvailable" class="actions">
              <el-button v-if="batch.status !== 'completed' && taskControl(batch)?.execution?.state !== 'paused'" size="small" :disabled="!safeTaskControl(batch) || !!busy" :title="taskControlReason(batch)" @click="act(batch, 'pause')">暂停</el-button>
              <el-button v-if="taskControl(batch)?.execution?.state === 'paused'" size="small" :disabled="!safeTaskControl(batch) || !!busy" :title="taskControlReason(batch)" @click="act(batch, 'resume')">继续</el-button>
              <el-button v-if="batch.failed_segments > 0" size="small" type="warning" :disabled="!safeTaskControl(batch) || !!busy" :title="taskControlReason(batch)" @click="act(batch, 'retry_failed')">重试可恢复失败分段</el-button>
              <el-button v-if="nightWindowsAvailable" size="small" :disabled="!safeTaskControl(batch) || !!busy" @click="openSchedule(batch)">执行时段</el-button>
              <el-button size="small" :disabled="!safeTaskControl(batch) || !!busy" @click="act(batch, 'reconcile')">核对并修复状态</el-button>
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
          <p v-if="!taskControlsAvailable" class="recovery">后端未声明任务级控制能力；升级后可暂停、继续或恢复此任务。</p>
          <p v-else-if="!safeTaskControl(batch)" class="recovery">{{ taskControlReason(batch) }}</p>
          <p v-if="taskControl(batch)?.execution && batch.status !== 'completed'" class="recovery">当前任务：{{ statusText(taskControl(batch).execution.state) }}<template v-if="taskControl(batch).execution.pause_reason"> · {{ pauseReasonText(taskControl(batch).execution.pause_reason) }}</template></p>
          <p v-if="taskControl(batch)?.execution?.next_eligible_at" class="recovery">北京时间预计可执行：{{ formatDateTime(taskControl(batch).execution.next_eligible_at, 'Asia/Shanghai') }}</p>
          <div v-if="segmentRecoveryAvailable" class="diagnostics">
            <header><h4>失败分段诊断</h4><el-button size="small" :loading="diagnosticLoading[batch.id]" :disabled="!canView" @click="loadSegments(batch, 1)">查看／刷新</el-button></header>
            <template v-if="segmentState[batch.id]?.segments">
              <el-table :data="segmentState[batch.id].segments" size="small" :row-key="row => row.id" @selection-change="rows => selectSegments(batch.id, rows)">
                <el-table-column type="selection" width="42" :selectable="row => row.can_retry === true" />
                <el-table-column prop="sequence" label="分段" width="64" />
                <el-table-column label="日期范围（UTC）" min-width="190"><template #default="{ row }">{{ formatDateTime(row.time_from, 'UTC') }} 至 {{ formatDateTime(row.time_to, 'UTC') }}</template></el-table-column>
                <el-table-column label="异常" min-width="190"><template #default="{ row }"><strong>{{ failureCategoryLabel(row.category) }}</strong><small v-if="row.error_code">错误码：{{ row.error_code }}</small><p>{{ row.error_message }}</p><small v-if="row.guidance">处理建议：{{ row.guidance }}</small><small v-if="row.blocked_reason">重试受限：{{ row.blocked_reason }}</small></template></el-table-column>
                <el-table-column label="断点／运行" min-width="180"><template #default="{ row }"><span>{{ progressLabel(row.detail_progress) }} · 第 {{ row.attempt || 0 }} 次尝试</span><el-button v-if="row.run_id && auth.hasPermission('integrations.view')" link type="primary" @click="goRun(row.run_id)">运行详情</el-button></template></el-table-column>
              </el-table>
              <p v-if="segmentState[batch.id].execution" class="recovery">任务状态：{{ statusText(segmentState[batch.id].execution.state) }}<template v-if="segmentState[batch.id].execution.pause_reason"> · {{ pauseReasonText(segmentState[batch.id].execution.pause_reason) }}</template></p>
              <el-pagination v-if="segmentState[batch.id].total > 20" small layout="prev, pager, next" :page-size="20" :total="segmentState[batch.id].total" :current-page="segmentState[batch.id].page" @current-change="page => loadSegments(batch, page)" />
              <div v-if="canManage && taskControlsAvailable" class="actions recovery-actions">
                <el-button size="small" type="warning" :disabled="!safeTaskControl(batch) || !selectedSegmentIds[batch.id]?.length || !!busy" @click="retrySelected(batch)">重试所选失败分段（{{ selectedSegmentIds[batch.id]?.length || 0 }}）</el-button>
                <el-button size="small" :disabled="!safeTaskControl(batch) || !!busy" @click="act(batch, 'retry_failed')">重试当前任务可恢复失败</el-button>
              </div>
            </template>
            <el-alert v-if="segmentState[batch.id]?.error" type="error" :closable="false" :title="segmentState[batch.id].error" />
            <nav class="recovery-links" aria-label="恢复指引">
              <el-button v-if="storeId(batch) && canViewStore" link type="primary" @click="goStore(storeId(batch))">店铺授权</el-button>
              <el-button v-if="configId(batch) && auth.hasPermission('integrations.config.view')" link type="primary" @click="goConfig(configId(batch))">连接配置</el-button>
              <el-button v-if="auth.hasPermission('integrations.store.view')" link type="primary" @click="router.push('/integrations/capabilities')">能力页面</el-button>
            </nav>
          </div>
        </article>
      </section>
    </template>
    <el-dialog v-model="scheduleDialog" title="设置此任务的执行时段" width="min(420px, 94vw)">
      <el-radio-group v-model="scheduleForm.mode"><el-radio-button value="anytime">随时执行</el-radio-button><el-radio-button value="night">夜间窗口</el-radio-button></el-radio-group>
      <div v-if="scheduleForm.mode === 'night'" class="dates schedule-fields"><el-form-item label="北京时间开始"><el-time-picker v-model="scheduleForm.start_time" value-format="HH:mm" /></el-form-item><el-form-item label="北京时间结束"><el-time-picker v-model="scheduleForm.end_time" value-format="HH:mm" /></el-form-item></div>
      <p v-if="scheduleValidationFor(scheduleForm)" class="error">{{ scheduleValidationFor(scheduleForm) }}</p>
      <template #footer><el-button @click="scheduleDialog = false">取消</el-button><el-button type="primary" :disabled="!safeTaskControl(scheduleBatch) || !!scheduleValidationFor(scheduleForm) || !!busy" @click="saveSchedule">保存</el-button></template>
    </el-dialog>
  </el-drawer>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { actOnHistorySyncBatch, createHistorySyncBatch, fetchHistorySyncBatches } from '../api/integrations';
import { useAuthStore } from '../stores/auth';

const props = defineProps({ modelValue: { type: Boolean, default: false }, job: { type: Object, default: null } });
defineEmits(['update:modelValue']);
const auth = useAuthStore();
const router = useRouter();
const canView = computed(() => auth.hasPermission('integrations.history.view'));
const canManage = computed(() => auth.hasPermission('integrations.history.manage') && auth.hasPermission('integrations.run_live_readonly'));
const form = reactive({ start_date: '', end_date: '', advertising_datasets: ['campaign_daily', 'shop_daily'], execution_mode: 'anytime', start_time: '00:30', end_time: '06:00' });
const busy = ref(''), loading = ref(false), loadError = ref(''), batches = ref([]);
const features = ref(null), featuresLoaded = ref(false), segmentState = reactive({}), selectedSegmentIds = reactive({}), diagnosticLoading = reactive({});
const scheduleDialog = ref(false), scheduleBatch = ref(null), scheduleForm = reactive({ mode: 'anytime', start_time: '00:30', end_time: '06:00' });
let submittedRequest = null, requestSequence = 0, diagnosticsSequence = 0, mutationSequence = 0, activeMutation = 0, timer = null, unmounted = false;
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
const resourceLabels = { sales_order: '销售订单', refund_return: '退货退款', settlement_bill: '财务流水', advertising_report: '广告报表' };
const advertisingDatasets = [
  { value: 'campaign_daily', label: '广告活动每日' }, { value: 'shop_daily', label: '店铺每日' },
  { value: 'campaign_hourly', label: '广告活动每小时' }, { value: 'shop_hourly', label: '店铺每小时' },
  { value: 'gms_campaign', label: 'GMS 广告活动' }, { value: 'gms_item', label: 'GMS 商品' },
];
const isAdvertising = computed(() => props.job?.resource_type === 'advertising_report');
const featureEnabled = name => Array.isArray(features.value) ? features.value.includes(name) : features.value?.[name] === true;
const advertisingAvailable = computed(() => featureEnabled('advertising_backfill'));
const nightWindowsAvailable = computed(() => featureEnabled('night_windows'));
const taskControlsAvailable = computed(() => featureEnabled('task_controls'));
const segmentRecoveryAvailable = computed(() => featureEnabled('segment_recovery'));
const canViewStore = computed(() => auth.hasPermission('masterdata.view') || auth.hasPermission('integrations.store_mapping.view'));
const regionTimezones = { SG: 'Asia/Singapore', MY: 'Asia/Kuala_Lumpur', TH: 'Asia/Bangkok', VN: 'Asia/Ho_Chi_Minh', PH: 'Asia/Manila', TW: 'Asia/Taipei', BR: 'America/Sao_Paulo', ID: 'Asia/Jakarta' };
const shopTimezone = computed(() => props.job?.store_timezone || props.job?.site_timezone || props.job?.store_authorization?.timezone
  || regionTimezones[String(props.job?.region || props.job?.store_region || props.job?.store_authorization?.region || '').toUpperCase()] || '');
const shopToday = computed(() => {
  if (!shopTimezone.value) return '';
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: shopTimezone.value }).format(new Date()); }
  catch { return ''; }
});
const cutoffDate = computed(() => shopToday.value ? subtractMonthsClamped(shopToday.value, 6) : '');
const canOperateJob = computed(() => props.job?.platform === 'shopee'
  && ['sales_order', 'refund_return', 'settlement_bill', 'advertising_report'].includes(props.job.resource_type)
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
  if (isAdvertising.value) {
    if (shopToday.value && end > shopToday.value) return '结束日期不能晚于店铺站点今天。';
    if (cutoffDate.value && (start < cutoffDate.value || end < cutoffDate.value)) return '广告补采日期须在店铺站点最近 6 个月内。';
  } else if (end > today) return '结束日期不能晚于北京时间今天。';
  if (isAdvertising.value && (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000 < 1) return '广告补采至少选择连续 2 天。';
  if ((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000 > 3660) return '开始和结束日期间隔不能超过 3660 天。';
  return '';
});
const scheduleValidationFor = policy => {
  if ((policy.mode || policy.execution_mode) !== 'night') return '';
  if (!nightWindowsAvailable.value) return '当前后端未声明夜间窗口能力，请升级后再设置。';
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(policy.start_time || '') || !/^([01]\d|2[0-3]):[0-5]\d$/.test(policy.end_time || '')) return '请选择有效的开始和结束时间。';
  if (policy.start_time < '00:00' || policy.start_time >= '08:00' || policy.end_time <= policy.start_time || policy.end_time > '08:00') return '夜间窗口须在北京时间 00:00 至 08:00 内，且结束时间晚于开始时间。';
  return '';
};
const scheduleValidation = computed(() => scheduleValidationFor(form));
const validForm = computed(() => !validationMessage.value && !scheduleValidation.value && !!props.job?.id && canOperateJob.value
  && (!isAdvertising.value || (advertisingAvailable.value && form.advertising_datasets.length > 0)));
const createBlockReason = computed(() => {
  if (!canManage.value) return '当前账号缺少历史补采管理或真实只读执行权限；仍可查看已有进度。';
  if (!props.job) return '当前任务信息不可用。';
  if (!['sales_order', 'refund_return', 'settlement_bill', 'advertising_report'].includes(props.job.resource_type)) return '该资源类型不支持历史补采。';
  if (props.job.resource_type === 'advertising_report' && !advertisingAvailable.value) return '后端未声明广告补采能力，请升级后再使用。';
  if (!['pilot', 'production'].includes(props.job.environment) || props.job.platform !== 'shopee') return '仅支持 Shopee 实际任务。';
  if (!props.job.is_enabled || props.job.status === 'disabled') return '任务已停用；启用后才能创建补采，现有进度仍可查看。';
  if (props.job.blocked_reason) return `任务当前受阻：${props.job.blocked_reason}`;
  if (!['ready', 'not_required'].includes(props.job.capability_state)) return '只读能力未就绪；检查能力和授权后才能创建补采。';
  if (['queued', 'running'].includes(props.job.schedule_state) || props.job.status === 'running') return '任务正在排队或运行；请完成当前运行后再创建补采。';
  return '';
});
function resourceLabel(value) { return resourceLabels[value] || value || '未知类型'; }
function subtractMonthsClamped(value, months) {
  const [year, month, day] = value.split('-').map(Number);
  const target = new Date(Date.UTC(year, month - 1, 1));
  target.setUTCMonth(target.getUTCMonth() - months);
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(day, lastDay));
  return target.toISOString().slice(0, 10);
}
function disableFutureDate(date) {
  if (isAdvertising.value && shopToday.value) {
    const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    return day > shopToday.value;
  }
  return !isAdvertising.value && date.getTime() > new Date(`${today}T23:59:59+08:00`).getTime();
}
function percent(done, total) { return total ? Math.min(100, Math.round(done * 100 / total)) : 0; }
function statusText(status) { return ({ running: '运行中', queued: '排队中', paused: '已暂停', completed: '已完成', failed: '失败', partial: '部分失败', pending: '待处理', ready: '时段已就绪，等待调度', waiting_window: '等待夜间执行窗口', blocked: '受阻，需处理异常', invalid_schedule: '执行时段配置无效' })[status] || status || '未知'; }
function pauseReasonText(reason) { return ({ manual: '手动暂停', permission_changed: '操作权限已变化，请重新确认权限', legacy_batch_paused: '原批次暂停已保留' })[reason] || reason; }
function authorizationLabel(state) {
  if (!state) return '状态未知';
  if (state.expired) return '已过期';
  return ({ disabled: '续期未启用', not_due: '尚未到续期时间', manual_recovery: '需人工恢复', refreshing: '正在续期', retry_wait: '等待重试', due: '到期待执行', blocked: '授权受阻' })[state.state] || '状态未知';
}
const failureLabels = { execution_timeout: '执行超时', request_timeout: '平台请求超时', rate_limit: '平台限流', database_lock: '数据库锁冲突', authorization: '授权异常', configuration: '配置或能力异常', date_range: '日期范围异常', missing_run: '缺少运行记录', data_or_runtime: '数据或运行异常' };
function failureCategoryLabel(category) { return failureLabels[category] || '其他异常'; }
function formatDateTime(value, timeZone) {
  if (value === null || value === undefined || value === '') return '—';
  const date = typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value)) ? new Date(Number(value) * 1000) : new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(date);
}
function progressLabel(progress) {
  if (!progress || typeof progress !== 'object' || !Object.keys(progress).length) return '暂无断点信息';
  return `断点已处理 ${progress.completed_in_page ?? 0} 项／待处理 ${progress.remaining_in_page ?? 0} 项 · 本段请求 ${progress.requests_in_slice ?? 0} 次`;
}
function storeId(batch) { return segmentState[batch.id]?.store_id || props.job?.store_id || props.job?.store_authorization?.store_id || null; }
function configId(batch) { return segmentState[batch.id]?.integration_config_id || props.job?.integration_config_id || props.job?.config_id || null; }
function isCurrentJob(jobId) { return !unmounted && props.modelValue && String(props.job?.id || '') === String(jobId); }
function releaseMutation(token) { if (activeMutation === token) { activeMutation = 0; busy.value = ''; } }
function currentJobShops(batch) { return (batch.shops || []).filter(shop => String(shop.job_id) === String(props.job?.id)); }
function taskControl(batch) { return batch?.task_control || null; }
function safeTaskControl(batch) {
  const control = taskControl(batch);
  return taskControlsAvailable.value && control?.can_manage === true
    && String(control.sync_job_id) === String(props.job?.id)
    && typeof control.revision === 'string' && control.revision.length > 0;
}
function taskControlReason(batch) {
  if (!taskControlsAvailable.value) return '后端未声明任务级控制能力，请升级后再操作。';
  const control = taskControl(batch);
  if (!control) return '接口未返回任务级控制信息，请刷新或升级后端。';
  if (String(control.sync_job_id) !== String(props.job?.id)) return '接口返回的任务范围与当前任务不一致，已禁用操作。';
  return control.execution?.pause_reason || '当前任务状态不允许此操作。';
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
    features.value = result.data?.features && typeof result.data.features === 'object' ? result.data.features : null;
    featuresLoaded.value = true;
    batches.value = result.data?.batches || [];
    for (const key of Object.keys(segmentState)) if (!batches.value.some(batch => String(batch.id) === key)) delete segmentState[key];
  } catch (error) {
    if (unmounted || !props.modelValue || sequence !== requestSequence) return;
    batches.value = []; loadError.value = error?.message || '历史补采进度读取失败';
  } finally {
    if (!unmounted && props.modelValue && sequence === requestSequence) { loading.value = false; updateTimer(); }
  }
}
async function create() {
  if (!canManage.value || !validForm.value || busy.value) return;
  const job = props.job;
  const jobId = String(job.id), start = form.start_date, end = form.end_date;
  const payload = { name: `手动补采任务 #${job.id}`, job_ids: [job.id], start_date: start, end_date: end };
  if (job.resource_type === 'advertising_report') payload.advertising_datasets = [...form.advertising_datasets];
  if (nightWindowsAvailable.value) payload.execution_policy = form.execution_mode === 'night'
    ? { mode: 'night', timezone: 'Asia/Shanghai', start_time: form.start_time, end_time: form.end_time }
    : { mode: 'anytime' };
  const formSnapshot = JSON.stringify({ start_date: form.start_date, end_date: form.end_date, advertising_datasets: [...form.advertising_datasets], execution_mode: form.execution_mode, start_time: form.start_time, end_time: form.end_time });
  const token = ++mutationSequence; activeMutation = token; busy.value = 'confirm';
  try {
    await ElMessageBox.confirm(`将为任务 #${job.id}（${resourceLabel(job.resource_type)}）补采 ${start} 至 ${end}（含）。此操作只读平台并写入本地，不进入常规同步队列。继续？`, '确认任务手动补采', { type: 'warning' });
  } catch { releaseMutation(token); return; }
  if (!canManage.value || !canOperateJob.value || !validForm.value || !isCurrentJob(jobId) || JSON.stringify({ start_date: form.start_date, end_date: form.end_date, advertising_datasets: [...form.advertising_datasets], execution_mode: form.execution_mode, start_time: form.start_time, end_time: form.end_time }) !== formSnapshot) {
    if (isCurrentJob(jobId)) ElMessage.error('权限、任务或表单内容已变化，请重新检查后再提交。');
    releaseMutation(token); return;
  }
  busy.value = 'create';
  const signature = JSON.stringify(payload);
  if (!submittedRequest || submittedRequest.signature !== signature) submittedRequest = { signature, key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` };
  try {
    const result = await createHistorySyncBatch({ ...payload, idempotency_key: submittedRequest.key });
    if (!isCurrentJob(jobId) || activeMutation !== token) return;
    if (!result?.success) throw new Error(result?.message || '历史补采提交失败');
    ElMessage.success('补采任务已提交；请查看当前任务的历史进度。');
    await load();
  } catch (error) { if (isCurrentJob(jobId) && activeMutation === token) ElMessage.error(error?.message || '历史补采提交失败'); }
  finally { releaseMutation(token); }
}
async function act(batch, action) {
  if (!canManage.value || !safeTaskControl(batch) || busy.value) return;
  const jobId = String(props.job?.id || '');
  const batchId = String(batch.id);
  const expectedRevision = taskControl(batch).revision;
  if (!jobId) return;
  const token = ++mutationSequence; activeMutation = token; busy.value = `${batch.id}:${action}`;
  try {
    if (action === 'reconcile') {
      try { await ElMessageBox.confirm('将核对当前任务的批次与分段状态，并按服务端规则修复可恢复状态。继续？', '确认核对并修复状态', { type: 'warning' }); }
      catch { return; }
    }
    if (action === 'retry_failed') {
      try { await ElMessageBox.confirm(`将重试批次“${batch.name || batch.id}”中可恢复的失败分段。${batch.status === 'paused' ? '批次会保持暂停；如需继续，请单独点击“继续”。' : '本操作不会自动暂停批次。'}继续？`, '确认重试失败分段', { type: 'warning' }); }
      catch { return; }
    }
    if (!canManage.value || !isCurrentJob(jobId)) return;
    const currentBatch = batches.value.find(item => String(item.id) === batchId);
    if (!currentBatch || !safeTaskControl(currentBatch) || taskControl(currentBatch).revision !== expectedRevision) { ElMessage.error('任务状态已变化，请刷新后重新操作。'); return; }
    const payload = { sync_job_id: Number(jobId), expected_revision: expectedRevision };
    const result = await actOnHistorySyncBatch(currentBatch.id, action, payload);
    if (!isCurrentJob(jobId) || activeMutation !== token) return;
    if (!result?.success) throw new Error(result?.message || '批次操作失败');
    const diagnostics = result.data?.diagnostics || result.diagnostics;
    if (diagnostics) segmentState[batchId] = { ...segmentState[batchId], ...diagnostics };
    ElMessage.success(action === 'reconcile' ? '核对并修复状态请求已提交' : '任务操作已提交'); await load();
  } catch (error) { if (isCurrentJob(jobId) && activeMutation === token) ElMessage.error(error?.message || '批次操作失败'); }
  finally { releaseMutation(token); }
}
async function loadSegments(batch, page = 1) {
  if (!canView.value || !props.modelValue || !props.job?.id || !segmentRecoveryAvailable.value) return;
  const key = String(batch.id), jobId = String(props.job.id), sequence = ++diagnosticsSequence;
  segmentState[key] = { ...segmentState[key], syncJobId: jobId, requestSequence: sequence, page, error: '' };
  diagnosticLoading[key] = true;
  try {
    const result = await fetchHistorySyncBatches({ sync_job_id: props.job.id, batch_id: batch.id, segment_page: page });
    if (unmounted || !props.modelValue || String(props.job?.id) !== jobId || segmentState[key]?.syncJobId !== jobId || segmentState[key]?.requestSequence !== sequence) return;
    if (!result?.success) throw new Error(result?.message || '分段诊断读取失败');
    const data = result.data || {};
    segmentState[key] = { ...segmentState[key], ...data, requestSequence: sequence, page: data.page || page, segments: data.segments || [] };
  } catch (error) {
    if (!unmounted && props.modelValue && segmentState[key]?.requestSequence === sequence) segmentState[key] = { ...segmentState[key], error: error?.message || '分段诊断读取失败' };
  } finally {
    if (!unmounted && segmentState[key]?.requestSequence === sequence) diagnosticLoading[key] = false;
  }
}
function selectSegments(batchId, rows) { selectedSegmentIds[batchId] = rows.filter(row => row.can_retry === true).slice(0, 100).map(row => row.id); }
async function retrySelected(batch) {
  const ids = [...(selectedSegmentIds[batch.id] || [])];
  if (!ids.length || ids.length > 100 || !safeTaskControl(batch) || !canManage.value) return;
  const control = taskControl(batch), jobId = String(props.job?.id || '');
  const token = ++mutationSequence; activeMutation = token; busy.value = `${batch.id}:retry_selected`;
  try {
    try { await ElMessageBox.confirm(`将仅重试当前任务选中的 ${ids.length} 个可重试分段；暂停状态不会自动恢复。继续？`, '确认重试所选分段', { type: 'warning' }); }
    catch { return; }
    const currentBatch = batches.value.find(item => String(item.id) === String(batch.id));
    if (!canManage.value || !safeTaskControl(currentBatch) || !isCurrentJob(jobId)) return;
    if (taskControl(currentBatch).revision !== control.revision) { ElMessage.error('任务状态已变化，请刷新后重新选择分段。'); return; }
    const payload = { sync_job_id: Number(jobId), expected_revision: control.revision, segment_ids: ids };
    const result = await actOnHistorySyncBatch(currentBatch.id, 'retry_failed', payload);
    if (!isCurrentJob(jobId) || activeMutation !== token) return;
    if (!result?.success) throw new Error(result?.message || '分段重试失败');
    selectedSegmentIds[batch.id] = [];
    ElMessage.success('所选分段重试请求已提交'); await loadSegments(batch, segmentState[batch.id]?.page || 1); await load();
  } catch (error) { if (isCurrentJob(jobId) && activeMutation === token) ElMessage.error(error?.message || '分段重试失败'); }
  finally { releaseMutation(token); }
}
function openSchedule(batch) {
  if (!safeTaskControl(batch) || !nightWindowsAvailable.value) return;
  scheduleBatch.value = batch;
  const policy = taskControl(batch)?.execution?.policy || {};
  scheduleForm.mode = policy.mode === 'night' ? 'night' : 'anytime';
  scheduleForm.start_time = policy.start_time || '00:30'; scheduleForm.end_time = policy.end_time || '06:00';
  scheduleDialog.value = true;
}
async function saveSchedule() {
  const batch = scheduleBatch.value;
  if (!batch || !canManage.value || !safeTaskControl(batch) || scheduleValidationFor(scheduleForm)) return;
  const control = taskControl(batch), jobId = String(props.job?.id || '');
  const execution_policy = scheduleForm.mode === 'night' ? { mode: 'night', timezone: 'Asia/Shanghai', start_time: scheduleForm.start_time, end_time: scheduleForm.end_time } : { mode: 'anytime' };
  const policySnapshot = JSON.stringify({ ...scheduleForm });
  const token = ++mutationSequence; activeMutation = token; busy.value = `${batch.id}:set_schedule`;
  try {
    try { await ElMessageBox.confirm('仅更新当前任务的执行时段；暂停的任务不会因此自动继续。继续？', '确认修改执行时段', { type: 'warning' }); }
    catch { return; }
    if (!canManage.value || !safeTaskControl(batch) || !isCurrentJob(jobId) || JSON.stringify({ ...scheduleForm }) !== policySnapshot) {
      if (isCurrentJob(jobId) && JSON.stringify({ ...scheduleForm }) !== policySnapshot) ElMessage.error('执行时段已变化，请重新确认后保存。');
      return;
    }
    const currentBatch = batches.value.find(item => String(item.id) === String(batch.id));
    if (!safeTaskControl(currentBatch) || taskControl(currentBatch).revision !== control.revision) { ElMessage.error('任务状态已变化，请刷新后重新设置执行时段。'); return; }
    const result = await actOnHistorySyncBatch(currentBatch.id, 'set_schedule', { sync_job_id: Number(jobId), expected_revision: control.revision, execution_policy });
    if (!isCurrentJob(jobId) || activeMutation !== token) return;
    if (!result?.success) throw new Error(result?.message || '执行时段修改失败');
    scheduleDialog.value = false; ElMessage.success('当前任务执行时段已更新'); await load();
  } catch (error) { if (isCurrentJob(jobId) && activeMutation === token) ElMessage.error(error?.message || '执行时段修改失败'); }
  finally { releaseMutation(token); }
}
function goStore(storeId) { if (storeId) router.push({ path: '/master-data/stores', query: { store_id: String(storeId), panel: 'api' } }); }
function goConfig(configId) { if (configId) router.push(`/integrations/configs/${configId}`); }
function goRun(runId) { router.push(`/integrations/sync-runs/${runId}`); }
watch(() => [props.modelValue, props.job?.id], ([open, id]) => {
  requestSequence += 1;
  diagnosticsSequence += 1;
  activeMutation = ++mutationSequence;
  busy.value = '';
  scheduleDialog.value = false;
  if (timer) { globalThis.clearInterval(timer); timer = null; }
  if (!open) { loading.value = false; return; }
  batches.value = []; loadError.value = ''; features.value = null; featuresLoaded.value = false;
  for (const key of Object.keys(segmentState)) delete segmentState[key];
  for (const key of Object.keys(diagnosticLoading)) delete diagnosticLoading[key];
  for (const key of Object.keys(selectedSegmentIds)) delete selectedSegmentIds[key];
  if (id && canView.value) load();
}, { immediate: true });
watch(canView, allowed => {
  if (allowed && props.modelValue) load();
  else {
    requestSequence += 1;
    batches.value = [];
    for (const key of Object.keys(segmentState)) delete segmentState[key];
    for (const key of Object.keys(diagnosticLoading)) delete diagnosticLoading[key];
    for (const key of Object.keys(selectedSegmentIds)) delete selectedSegmentIds[key];
    loadError.value = '';
    loading.value = false;
    if (timer) { globalThis.clearInterval(timer); timer = null; }
  }
});
onUnmounted(() => { unmounted = true; requestSequence += 1; activeMutation = ++mutationSequence; if (timer) globalThis.clearInterval(timer); timer = null; });
</script>

<style scoped>
.notice,.recovery{color:#475569;font-size:13px;line-height:1.55}.form{margin-top:18px}.dates{display:grid;grid-template-columns:1fr 1fr;gap:12px}.dates :deep(.el-date-editor),.form :deep(.el-select){width:100%}.legacy{margin-top:28px}.legacy header,.batch-heading,.diagnostics header{display:flex;align-items:center;justify-content:space-between;gap:12px}.legacy h3{font-size:16px}.batch{padding:14px 0;border-bottom:1px solid #e2e8f0}.batch-heading small,.batch small{display:block;color:#64748b;font-size:12px}.actions{display:flex;gap:6px;flex-wrap:wrap}.shop{margin:12px 0;padding:12px;border:1px solid #e2e8f0;border-radius:8px}.error{color:#b91c1c;font-size:13px}.diagnostics{margin-top:14px;padding:12px;border:1px solid #dbe3ec;border-radius:8px}.diagnostics h4{margin:6px 0;font-size:14px}.diagnostics :deep(.el-table){max-width:100%}.diagnostics :deep(.el-table p){margin:4px 0;white-space:normal}.recovery-actions,.recovery-links{margin-top:10px}.schedule-fields{margin-top:18px}@media(max-width:640px){.dates{grid-template-columns:1fr}.batch-heading,.diagnostics header{align-items:flex-start;flex-direction:column}.actions{width:100%}.actions :deep(.el-button){margin-left:0}}
</style>
