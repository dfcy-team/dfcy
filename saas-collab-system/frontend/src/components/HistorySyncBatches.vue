<template>
  <section class="history-batches" aria-label="Shopee 历史数据补采">
    <header><div><h2>Shopee 历史补采</h2><p>可同时选择多个店铺和数据类型，系统自动拆分为最多 15 天的批次。</p></div>
      <div class="actions"><el-button v-if="canManage" type="primary" @click="openCreate">创建历史同步</el-button><el-button :loading="loading" @click="load">刷新</el-button></div>
    </header>
    <el-alert type="warning" :closable="false" show-icon title="平台可能不会保留所选日期的全部数据；进度表示已处理的分段，不代表历史覆盖完整。" />
    <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" />
    <el-empty v-if="!loading && !loadError && !batches.length" description="暂无历史同步批次" />
    <article v-for="batch in batches" :key="batch.id" class="batch">
      <div class="batch-heading"><div><strong>{{ batch.name || `历史同步 #${batch.id}` }}</strong><small>{{ batch.start_date }} 至 {{ batch.end_date }} · {{ statusText(batch.status) }}</small></div>
        <div v-if="canManage" class="actions">
          <el-button size="small" :disabled="!!busy || !batch.range_adjustment?.allowed || batch.status === 'running'" :title="batch.range_adjustment?.blocked_reason || (batch.status === 'running' ? '请先暂停批次再调整范围' : '')" @click="openRangeAdjustment(batch)">调整补采范围</el-button>
          <el-button v-if="batch.status === 'running'" size="small" :loading="busy === `${batch.id}:pause`" :disabled="!!busy" @click="act(batch,'pause')">暂停</el-button>
          <el-button v-if="batch.status === 'paused'" size="small" :loading="busy === `${batch.id}:resume`" :disabled="!!busy" @click="act(batch,'resume')">继续</el-button>
          <el-button v-if="batch.failed_segments > 0" size="small" type="warning" :title="`只重试静态校验可恢复的失败分段；无效或正在运行的分段会保留并跳过。${retryFailedStateHint(batch)}`" :loading="busy === `${batch.id}:retry_failed`" :disabled="!!busy" @click="act(batch,'retry_failed')">重试可恢复失败分段</el-button>
        </div>
      </div>
      <el-progress :percentage="percent(batch.success_segments + batch.failed_segments, batch.total_segments)" :status="batch.failed_segments ? 'exception' : undefined" />
      <small>分段 {{ batch.success_segments || 0 }} 成功 / {{ batch.failed_segments || 0 }} 失败 / {{ batch.total_segments || 0 }} 总计 · 已获取 {{ batch.fetched_count || 0 }} 条</small>
      <div class="shops">
        <div v-for="shop in batch.shops || []" :key="shop.job_id" class="shop"><div><strong>{{ shop.shop_name }} · {{ resourceLabel(shop.resource_type) }}</strong><span>{{ statusText(shop.status) }}</span></div>
          <el-progress :percentage="percent((shop.success_segments || 0) + (shop.failed_segments || 0), shop.total_segments)" :status="shop.failed_segments ? 'exception' : undefined" />
          <small>{{ shop.success_segments || 0 }}/{{ shop.total_segments || 0 }} 分段 · {{ shop.fetched_count || 0 }} 条</small>
          <p class="authorization">当前授权：{{ authorizationLabel(shop.authorization) }}<template v-if="shop.authorization?.expires_at"> · 到期 {{ shop.authorization.expires_at }}</template><template v-if="shop.recovery_hint"> · {{ shop.recovery_hint }}</template></p>
          <p v-if="shop.waiting_for_refresh != null && shop.waiting_for_refresh > 0" class="authorization">等待授权续期：{{ shop.waiting_for_refresh }} 个分段</p>
          <p v-if="shop.last_error" class="error">历史运行错误：{{ shop.last_error }}</p>
        </div>
      </div>
    </article>

    <el-dialog v-model="rangeDialog" title="调整历史补采范围" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <div class="dates"><el-form-item label="开始日期"><el-date-picker v-model="rangeForm.start_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item><el-form-item label="结束日期（含）"><el-date-picker v-model="rangeForm.end_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item></div>
        <p v-if="rangeProtectedText" class="authorization">已提交或处理过的范围 {{ rangeProtectedText }} 为保护区间，调整后必须完整包含。</p>
        <el-alert type="info" :closable="false" title="日期按北京时间理解且包含结束日；调整后批次保持暂停，已有结果和检查点会保留。" />
        <p v-if="rangeValidationMessage" class="error">{{ rangeValidationMessage }}</p>
        <p v-if="rangeError" class="error">{{ rangeError }}</p>
      </el-form>
      <template #footer><el-button @click="rangeDialog=false">取消</el-button><el-button type="primary" :loading="busy==='range_adjustment'" :disabled="!canManage || !validRange || !!busy" @click="submitRangeAdjustment">确认调整并保持暂停</el-button></template>
    </el-dialog>

    <el-dialog v-model="dialog" title="创建 Shopee 历史补采" width="min(560px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="批次名称"><el-input v-model="form.name" maxlength="100" placeholder="可选" /></el-form-item>
        <el-form-item label="店铺与数据类型（可多选）"><el-select v-model="form.job_ids" multiple filterable style="width:100%" placeholder="选择已启用的 Shopee 同步任务"><el-option v-for="job in eligibleJobs" :key="job.id" :value="job.id" :label="`${job.shop_name} · ${resourceLabel(job.resource_type)}`" /></el-select><small v-if="missingResourceTypes.length" class="missing-types">尚未找到以下类型的可用任务：{{ missingResourceTypes.map(resourceLabel).join('、') }}。请先创建对应同步任务。</small></el-form-item>
        <div class="dates"><el-form-item label="开始日期"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item><el-form-item label="结束日期（含）"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" :disabled-date="disableFutureDate" /></el-form-item></div>
        <el-alert type="warning" :closable="false" title="日期按北京时间理解且包含结束日；平台可能无法提供所有历史日期的数据。" />
      </el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="busy==='create'" :disabled="!canManage || !validForm || !!busy" @click="create">确认开始</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { actOnHistorySyncBatch, createHistorySyncBatch, fetchHistorySyncBatches } from '../api/integrations';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const canView = computed(() => auth.hasPermission('integrations.history.view'));
function hasManagePermissions() { return auth.hasPermission('integrations.history.manage') && auth.hasPermission('integrations.run_live_readonly'); }
const canManage = computed(hasManagePermissions);
const batches = ref([]), jobs = ref([]), loading = ref(false), loadError = ref(''), busy = ref(''), dialog = ref(false), timer = ref(null);
const rangeDialog = ref(false), rangeBatch = ref(null), rangeRevision = ref(''), rangeError = ref('');
const rangeForm = reactive({ start_date: '', end_date: '' });
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
const form = reactive({ name: '', job_ids: [], start_date: '', end_date: '' });
let submittedRequest = null;
let loadRequestSequence = 0;
let unmounted = false;
function disableFutureDate(date) { return date.getTime() > new Date(`${today}T23:59:59+08:00`).getTime(); }
const resourceTypes = ['sales_order', 'refund_return', 'settlement_bill'];
const resourceLabels = { sales_order: '销售订单', refund_return: '退货退款', settlement_bill: '财务流水' };
function resourceLabel(value) { return resourceLabels[value] || value || '未知类型'; }
const eligibleJobs = computed(() => jobs.value.filter(job => job.is_enabled && !job.blocked_reason && resourceTypes.includes(job.resource_type)));
const missingResourceTypes = computed(() => resourceTypes.filter(type => !eligibleJobs.value.some(job => job.resource_type === type)));
const validForm = computed(() => form.job_ids.length > 0 && form.job_ids.length <= 100 && form.start_date && form.end_date && form.start_date <= form.end_date && form.end_date <= today);
const rangeAdjustment = computed(() => rangeBatch.value?.range_adjustment || {});
const rangeProtectedText = computed(() => rangeAdjustment.value.protected_start_date && rangeAdjustment.value.protected_end_date ? `${rangeAdjustment.value.protected_start_date} 至 ${rangeAdjustment.value.protected_end_date}` : '');
const rangeValidationMessage = computed(() => {
  const { start_date: start, end_date: end } = rangeForm;
  if (!start || !end) return '请选择开始日期和结束日期。';
  const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
  if (!validDate(start) || !validDate(end)) return '请输入有效的 YYYY-MM-DD 日历日期。';
  if (start > end) return '开始日期不能晚于结束日期。';
  if (end > today) return '结束日期不能晚于北京时间今天。';
  if (start === rangeBatch.value?.start_date && end === rangeBatch.value?.end_date) return '新范围必须与当前范围不同。';
  const dayDifference = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000;
  if (dayDifference > 3660) return '开始和结束日期间隔不能超过 3660 天。';
  const protectedStart = rangeAdjustment.value.protected_start_date, protectedEnd = rangeAdjustment.value.protected_end_date;
  if ((protectedStart && start > protectedStart) || (protectedEnd && end < protectedEnd)) return '新范围必须完整包含所有已提交或处理过的保护区间。';
  return '';
});
const validRange = computed(() => !rangeValidationMessage.value);
function percent(done, total) { return total ? Math.min(100, Math.round(done * 100 / total)) : 0; }
function statusText(status) { return ({ running:'运行中', queued:'排队中', paused:'已暂停', completed:'已完成', failed:'失败', partial:'部分失败', pending:'待处理' })[status] || status || '未知'; }
function retryFailedStateHint(batch) {
  return batch?.status === 'paused'
    ? '批次已暂停，重试后仍保持暂停；如需继续，请单独点击“继续”。'
    : '如果批次已暂停，重试后仍保持暂停；未暂停时本操作不会暂停批次，批次可能保持或进入运行状态。';
}
function authorizationLabel(auth) {
  if (!auth) return '状态未知（接口未提供）';
  if (auth.expired) return '已过期';
  return ({ disabled:'续期未启用', not_due:'尚未到续期时间', manual_recovery:'需人工恢复', refreshing:'正在续期', retry_wait:'等待重试', due:'到期待执行', blocked:'授权受阻' })[auth.state] || '状态未知';
}
async function load() {
  if (unmounted || !canView.value) return;
  const requestSequence = ++loadRequestSequence;
  loading.value = true; loadError.value = '';
  try {
    const r = await fetchHistorySyncBatches();
    if (unmounted || requestSequence !== loadRequestSequence) return;
    if (!r?.success) throw new Error(r?.message || '历史同步读取失败');
    batches.value = r.data?.batches || []; jobs.value = r.data?.jobs || []; updateTimer();
  }
  catch (e) {
    if (unmounted || requestSequence !== loadRequestSequence) return;
    batches.value = []; jobs.value = []; loadError.value = e?.message || '历史同步读取失败'; ElMessage.error(loadError.value);
  }
  finally { if (!unmounted && requestSequence === loadRequestSequence) loading.value = false; }
}
function openCreate() { if (!canManage.value) return; submittedRequest = null; form.name = ''; form.job_ids = []; form.start_date = ''; form.end_date = ''; dialog.value = true; }
async function create() {
  if (!canManage.value || !validForm.value || busy.value) return;
  try { await ElMessageBox.confirm(`将为 ${form.job_ids.length} 个店铺数据任务创建 ${form.start_date} 至 ${form.end_date}（含） 的只读历史补采。平台可能不保留全部日期。继续？`, '确认开始历史补采', { type:'warning' }); }
  catch { return; }
  busy.value = 'create';
  try {
    const payload = { name: form.name.trim(), job_ids: [...form.job_ids], start_date: form.start_date, end_date: form.end_date };
    const signature = JSON.stringify(payload);
    if (!submittedRequest || submittedRequest.signature !== signature) submittedRequest = { signature, key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` };
    const r = await createHistorySyncBatch({ ...payload, idempotency_key: submittedRequest.key }); if (!r?.success) throw new Error(r?.message || '提交失败'); ElMessage.success('历史同步已提交'); dialog.value = false; await load();
  }
  catch (e) { ElMessage.error(e?.message || '历史同步提交失败'); }
  finally { busy.value = ''; }
}
async function act(batch, action) {
  if (!canManage.value || busy.value) return;
  if (action === 'retry_failed') { try { await ElMessageBox.confirm(`将重试批次“${batch.name || batch.id}”中经静态校验可恢复的失败分段；无效或正在运行的分段会保留并跳过。${retryFailedStateHint(batch)}`, '确认重试', { type:'warning' }); } catch { return; } }
  busy.value = `${batch.id}:${action}`;
  try { const r = await actOnHistorySyncBatch(batch.id, action); if (!r?.success) throw new Error(r?.message || '操作失败'); ElMessage.success('操作已提交'); await load(); }
  catch (e) { ElMessage.error(e?.message || '操作失败'); }
  finally { busy.value = ''; }
}
function openRangeAdjustment(batch) {
  if (!canManage.value || !batch?.range_adjustment?.allowed || batch.status === 'running' || busy.value) return;
  rangeBatch.value = batch;
  rangeRevision.value = batch.range_adjustment.revision;
  rangeForm.start_date = batch.start_date;
  rangeForm.end_date = batch.end_date;
  rangeError.value = '';
  rangeDialog.value = true;
}
async function submitRangeAdjustment() {
  if (!canManage.value || !validRange.value || busy.value || !rangeBatch.value) return;
  busy.value = 'range_adjustment';
  rangeError.value = '';
  const batchId = rangeBatch.value.id;
  const expectedRevision = rangeRevision.value;
  const { start_date, end_date } = rangeForm;
  const oldStart = rangeBatch.value.start_date, oldEnd = rangeBatch.value.end_date;
  try {
    try { await ElMessageBox.confirm(`将批次范围从 ${oldStart} 至 ${oldEnd} 调整为 ${start_date} 至 ${end_date}（北京时间，含结束日）。已有结果和检查点会保留，调整后批次保持暂停。继续？`, '确认调整补采范围', { type:'warning' }); }
    catch { return; }
    if (!hasManagePermissions()) { rangeError.value = '权限已变化，请重新检查权限后再调整。'; return; }
    const r = await actOnHistorySyncBatch(batchId, 'adjust_range', { start_date, end_date, expected_revision: expectedRevision });
    if (!r?.success) throw Object.assign(new Error(r?.message || '范围调整失败'), { code: r?.code });
    ElMessage.success('补采范围已调整，批次保持暂停');
    rangeDialog.value = false;
    await load();
  } catch (e) {
    const stale = e?.code === 'STALE_REVISION' || /stale|revision|补采范围或分段状态已变化|范围已变化/i.test(e?.message || '');
    rangeError.value = stale ? '补采范围或分段状态已变化，请刷新批次后重新调整。请关闭此对话框并重新打开，以使用最新版本。' : (e?.message || '范围调整失败');
    ElMessage.error(rangeError.value);
    if (stale) await load();
  } finally { busy.value = ''; }
}
function updateTimer() {
  const active = batches.value.some(b => ['running','queued'].includes(b.status));
  if (active && !timer.value) timer.value = globalThis.setInterval(load, 10000);
  if (!active && timer.value) { globalThis.clearInterval(timer.value); timer.value = null; }
}
onMounted(load);
onUnmounted(() => { unmounted = true; loadRequestSequence += 1; if (timer.value) globalThis.clearInterval(timer.value); timer.value = null; });
</script>

<style scoped>
.history-batches{margin:0 0 24px;padding:18px;border:1px solid #dbe3ec;border-radius:10px;background:#fff}.history-batches header,.batch-heading,.batch-heading>div,.shop>div:first-child,.actions{display:flex;align-items:center;justify-content:space-between;gap:12px}.history-batches h2{margin:0;font-size:18px}.history-batches header p,.batch small,.batch-heading small{display:block;color:#64748b;font-size:12px}.history-batches header p{margin:5px 0 12px}.batch{padding:16px 0;border-bottom:1px solid #e2e8f0}.batch:last-child{border-bottom:0}.batch-heading{margin-bottom:10px}.batch-heading small{margin-top:4px}.shops{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:12px}.shop{padding:12px;border:1px solid #e2e8f0;border-radius:8px}.shop>div:first-child span{color:#64748b;font-size:12px}.missing-types{display:block;margin-top:5px;color:#b45309;line-height:1.5}.authorization{margin:6px 0 0;color:#475569;font-size:12px;overflow-wrap:anywhere}.error{margin:6px 0 0;color:#b91c1c;font-size:12px;overflow-wrap:anywhere}.dates{display:grid;grid-template-columns:1fr 1fr;gap:12px}.dates :deep(.el-date-editor){width:100%}@media(max-width:640px){.history-batches header,.batch-heading{align-items:flex-start;flex-direction:column}.actions{flex-wrap:wrap}}
</style>
