<template>
  <section class="schedule-settings">
    <h3>采集范围与定时设置</h3>
    <p>采集范围决定读取哪些数据，定时设置决定何时执行。保存不会立即采集，也不会启用停用任务。</p>
    <el-form label-position="top" :disabled="!canManage || saving">
      <template v-if="supportsRange">
        <el-form-item label="采集范围">
          <el-select v-model="form.query_mode"><el-option label="每次回看最近 N 天" value="incremental" /><el-option label="指定起止日期（历史补采）" value="range" /></el-select>
        </el-form-item>
        <el-form-item v-if="form.query_mode === 'incremental'" :label="`回看天数（1～${maxDays}）`"><el-input-number v-model="form.lookback_days" :min="1" :max="maxDays" :precision="0" /></el-form-item>
        <template v-else>
          <el-form-item label="开始日期（北京时间）"><el-date-picker v-model="form.range_start_at" type="date" value-format="YYYY-MM-DD" placeholder="选择开始日期" style="width:100%" /></el-form-item>
          <el-form-item label="结束日期（北京时间，包含当天）"><el-date-picker v-model="form.range_end_at" type="date" value-format="YYYY-MM-DD" placeholder="选择结束日期" style="width:100%" /></el-form-item>
          <p>按北京时间整日采集，今天采集至执行时刻。含首尾日期最多 {{ maxDays }} 天；固定范围会在后续每次执行时重复使用，补采后请改回最近 N 天。</p>
        </template>
        <p>{{ collectionBasis }} 最近 N 天包含今天，按北京时间从首日 00:00 采集至执行时刻，不等于只采集上次成功之后的数据。历史记录幂等更新。</p>
      </template>
      <p v-else>该任务不使用订单/退款时间范围：商品按现有全量或增量策略读取，库存读取当前快照。</p>
      <el-form-item label="执行方式"><el-select v-model="form.schedule_type"><el-option label="手动" value="manual" /><el-option label="每隔 N 分钟" value="interval" /><el-option label="每天" value="daily" /><el-option label="每周" value="weekly" /></el-select></el-form-item>
      <el-form-item v-if="form.schedule_type === 'interval'" label="间隔（分钟，15～10080）"><el-input-number v-model="form.interval_minutes" :min="15" :max="10080" /></el-form-item>
      <el-form-item v-if="['daily','weekly'].includes(form.schedule_type)" label="执行时间（所选时区）"><el-time-select v-model="form.local_time" start="00:00" step="00:15" end="23:45" /></el-form-item>
      <el-form-item v-if="form.schedule_type === 'weekly'" label="星期"><el-checkbox-group v-model="form.weekdays"><el-checkbox v-for="(day, i) in days" :key="day" :label="i + 1">{{ day }}</el-checkbox></el-checkbox-group></el-form-item>
      <el-form-item label="计划时区"><el-select v-model="form.timezone"><el-option label="北京时间 UTC+8" value="Asia/Shanghai" /><el-option label="菲律宾时间 UTC+8" value="Asia/Manila" /><el-option label="协调世界时 UTC" value="UTC" /><el-option v-if="!['Asia/Shanghai','Asia/Manila','UTC'].includes(form.timezone)" :label="form.timezone" :value="form.timezone" /></el-select></el-form-item>
      <el-form-item label="错过执行（超出计划时点 60 秒）"><el-radio-group v-model="form.catch_up"><el-radio label="skip">跳过</el-radio><el-radio label="run_once">恢复后补跑一次</el-radio></el-radio-group></el-form-item>
      <el-form-item label="暂停至（含时区，可留空）"><el-input v-model="form.pause_until" clearable placeholder="例如 2026-09-15T09:00:00+08:00" /></el-form-item>
    </el-form>
    <p>失败重试：最多 {{ job.max_retry_count ?? '—' }} 次，指数退避（基础 {{ job.backoff_base_seconds ?? '—' }} 秒）；不改变正常计划。</p>
    <p v-if="job.schedule_type === 'cron'">旧 Cron 计划不派发；请改为间隔、每日或每周后保存。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="schedule-actions"><el-button :disabled="!canManage || saving" :loading="previewing" @click="preview">预览范围与计划</el-button><el-button type="primary" :disabled="!canManage || !previewed || previewing" :loading="saving" @click="save">保存设置（不执行）</el-button></div>
    <p v-if="collectionRange">本次预览采集日期（北京时间）：{{ syncCollectionDate(collectionRange.time_from) }} 至 {{ syncCollectionDate(collectionRange.time_to) }}。包含结束日，今天截至执行时刻；最近 N 天在实际执行时重新计算。</p>
    <ol v-if="times.length"><li v-for="value in times" :key="value">{{ localTime(value) }}（{{ form.timezone }}）<small>{{ syncTime(value) }} UTC</small></li></ol>
    <p v-else-if="previewed">手动任务无计划执行时间。</p>
    <p>保存不会触发立即同步；启用后仍需后台调度服务持续运行，并通过每次执行的授权和只读准入校验。</p>
  </section>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { requestApi } from '../api/request';
import { updateSyncJob } from '../api/integrations';
import { syncCollectionDate, syncError, syncTime } from '../utils/syncPresentation';
const props = defineProps({ job: { type: Object, required: true }, canManage: Boolean });
const emit = defineEmits(['saved']);
const supportsRange = computed(() => ['sales_order', 'refund_return'].includes(props.job.resource_type));
const maxDays = computed(() => props.job.platform === 'shopee' ? 15 : 30);
const collectionBasis = computed(() => props.job.resource_type === 'refund_return' ? '退款按申请创建时间采集。' : props.job.platform === 'shopee' ? 'Shopee 订单按更新时间采集。' : '订单按创建时间采集。');
const collectionRange = ref(null);
const form = reactive({}), times = ref([]), previewed = ref(false), previewing = ref(false), saving = ref(false), error = ref('');
const days = ['周一','周二','周三','周四','周五','周六','周日'];
watch(() => props.job, job => { Object.assign(form, { schedule_type: job.schedule_type === 'hourly' ? 'interval' : job.schedule_type === 'cron' ? 'manual' : job.schedule_type || 'manual', interval_minutes: job.interval_minutes || 60, local_time: job.local_time || '02:00', weekdays: [...(job.weekdays || [1])], timezone: job.timezone || 'Asia/Shanghai', catch_up: job.catch_up || 'skip', pause_until: job.pause_until || '' }); }, { immediate: true });
watch(() => props.job, job => {
  if (supportsRange.value) Object.assign(form, { query_mode: job.query_mode || 'incremental', lookback_days: job.lookback_days ?? 1, range_start_at: collectionDate(job.range_start_at), range_end_at: collectionDate(job.range_end_at) });
  else for (const key of ['query_mode', 'lookback_days', 'range_start_at', 'range_end_at']) delete form[key];
}, { immediate: true });
watch(form, () => { previewed.value = false; times.value = []; collectionRange.value = null; });
function localTime(value) { return new Intl.DateTimeFormat('zh-CN', { timeZone: form.timezone, dateStyle: 'short', timeStyle: 'medium', hour12: false }).format(new Date(value)); }
function collectionDate(value) {
  if (!value || /^\d{4}-\d{2}-\d{2}$/.test(value)) return value || '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 10);
}
async function preview() {
  if (!props.canManage || previewing.value) return;
  previewing.value = true; error.value = ''; previewed.value = false;
  const payload = JSON.stringify(form);
  try {
    const response = await requestApi({ method: 'post', url: `/api/internal/integrations/sync-jobs/${props.job.id}/schedule-preview/`, data: JSON.parse(payload) });
    if (!response.success) throw new Error(response.message);
    if (payload !== JSON.stringify(form)) return;
    times.value = response.data.times; collectionRange.value = response.data.collection_range; previewed.value = true;
  } catch (e) { error.value = syncError(e.message); }
  finally { previewing.value = false; }
}
async function save() {
  if (!props.canManage || !previewed.value || saving.value) return;
  saving.value = true; error.value = '';
  try {
    if (props.job.is_enabled) await ElMessageBox.confirm('任务当前已启用，新计划保存后将影响后续调度，不会立即执行。确认保存？', '确认计划变更');
    const response = await updateSyncJob(props.job.id, { ...form });
    if (!response.success) throw new Error(response.message);
    ElMessage.success('采集范围与计划已保存，未执行任务；启停状态保持不变。'); emit('saved');
  } catch (e) { if (e !== 'cancel' && e !== 'close') error.value = syncError(e.message); }
  finally { saving.value = false; }
}
</script>
<style scoped>
.schedule-settings { margin-top:20px; padding-top:16px; border-top:1px solid #dbe3ec; } h3 { margin:0; font-size:16px; } p,li { font-size:13px; line-height:1.6; color:#475569; } .el-select,.el-input { width:100%; } .schedule-actions { display:flex; gap:8px; margin:12px 0; } small { display:block; color:#64748b; }
</style>
