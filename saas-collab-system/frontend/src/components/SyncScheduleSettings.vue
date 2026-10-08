<template>
  <section class="schedule-settings">
    <h3>采集范围与定时设置</h3>
    <p>采集范围决定读取哪些数据，定时设置决定何时执行。保存不会立即采集，也不会启用停用任务。</p>
    <el-form label-position="top" :disabled="!canManage || saving">
      <el-form-item v-if="isProductJob && !isMissingOrdersOnly" label="商品采集方式">
        <el-select v-model="form.product_full_sync">
          <el-option label="全量采集" :value="true" />
          <el-option label="增量采集" :value="false" />
        </el-select>
        <p>全量采集不限制商品更新时间；增量采集仅读取所选范围内更新的商品。Shopee 常规列表仅使用已校验的 NORMAL 状态，不等于全部历史商品。</p>
      </el-form-item>
      <el-form-item v-if="supportsProductOrderBackfill" label="商品关联订单补齐策略">
        <el-select v-model="form.product_order_backfill">
          <el-option label="常规同步后补齐订单缺失商品 ID（默认）" value="catalog_and_order_missing" />
          <el-option label="仅常规商品同步" value="catalog_only" />
          <el-option label="仅补齐订单缺失商品 ID" value="order_missing_only" />
        </el-select>
        <p v-if="isMissingOrdersOnly">该策略不读取商品列表，也不按月或按商品时间范围限制；会检查本任务环境内、本店全部已落库订单的商品 ID 与变体 ID。保存不会立即运行。</p>
        <p v-else-if="form.product_order_backfill === 'catalog_and_order_missing'">先执行常规商品同步，再针对已持久化订单中缺失的商品关联进行补齐。常规同步只覆盖平台返回的记录，不保证找回平台已删除的商品。</p>
        <p v-else>仅执行常规商品同步；平台未返回的商品不会由此策略补齐。</p>
      </el-form-item>
      <template v-if="supportsEfficientPolicy">
        <el-form-item label="增量策略">
          <el-select v-model="form.strategy_profile">
            <el-option label="兼容策略" value="legacy" />
            <el-option label="高效采集" value="efficient_v1" />
          </el-select>
          <el-button v-if="hasRecommendation" text type="primary" @click="applyRecommendation">应用推荐策略</el-button>
          <p v-if="recommendation.notice">{{ recommendation.notice }}</p>
        </el-form-item>
        <el-form-item v-if="canEditAnchor" label="增量起点">
          <el-select v-model="form.incremental_anchor">
            <el-option label="回看最近 N 天" value="lookback" />
            <el-option label="从上次成功查询检查点继续" value="checkpoint" />
          </el-select>
          <p>检查点是上次真实成功查询的时间上界，不是任务完成时间。</p>
          <el-form-item v-if="form.incremental_anchor === 'checkpoint'" label="检查点重叠分钟（0～1440）">
            <el-input-number v-model="form.overlap_minutes" :min="0" :max="1440" :precision="0" />
          </el-form-item>
          <p v-if="isProductJob && form.strategy_profile === 'efficient_v1'">高效采集首次初始化会采集完整商品目录，之后读取增量目录。<template v-if="String(job.platform || '').toLowerCase() === 'shopee'">Shopee 还会补齐订单中缺失的商品 ID。</template></p>
        </el-form-item>
      </template>
      <template v-if="supportsRange">
        <el-form-item label="采集范围">
          <el-select v-model="form.query_mode" @change="applyModeDefault"><el-option label="每次回看最近 N 天" value="incremental" /><el-option label="指定起止日期（历史补采）" value="range" /></el-select>
        </el-form-item>
        <el-form-item v-if="isOrderJob" label="订单时间口径">
          <el-select v-model="form.collection_time_basis"><el-option label="创建时间（适合历史补采）" value="created" /><el-option label="更新时间（适合日常增量）" value="updated" /></el-select>
          <p>创建时间用于找回指定日期内创建的订单；更新时间用于持续采集状态、金额等后续变化。</p>
        </el-form-item>
        <el-form-item v-if="form.query_mode === 'incremental'" :label="`回看天数（1～${maxDays}）`"><el-input-number v-model="form.lookback_days" :min="1" :max="maxDays" :precision="0" /></el-form-item>
        <template v-else>
          <el-form-item label="开始日期（北京时间）"><el-date-picker v-model="form.range_start_at" type="date" value-format="YYYY-MM-DD" placeholder="选择开始日期" style="width:100%" /></el-form-item>
          <el-form-item label="结束日期（北京时间，包含当天）"><el-date-picker v-model="form.range_end_at" type="date" value-format="YYYY-MM-DD" placeholder="选择结束日期" style="width:100%" /></el-form-item>
          <p>按北京时间整日采集，今天采集至执行时刻。含首尾日期最多 {{ maxDays }} 天；固定范围会在后续每次执行时重复使用，补采后请改回最近 N 天。</p>
        </template>
        <p>{{ collectionBasis }}<template v-if="form.query_mode === 'range'">使用固定起止范围，保存后后续执行仍会重复该范围。</template><template v-else-if="form.strategy_profile === 'efficient_v1' && form.incremental_anchor === 'checkpoint' && canEditAnchor">优先从最近一次成功查询的上界继续；检查点不可用时按预览所示回退策略处理。</template><template v-else>按北京时间回看最近 {{ form.lookback_days }} 天，包含今天；每次执行重新计算范围。</template> 历史记录幂等更新。</p>
      </template>
      <p v-else-if="isMissingOrdersOnly">当前仅补齐订单缺失商品 ID，不限制日期；不读取商品列表，不改写历史订单。</p>
      <p v-else-if="isProductJob">当前为全量采集，不限制商品更新时间。</p>
      <p v-else>该任务不使用采集时间范围，库存读取当前快照。</p>
      <el-form-item label="执行方式"><el-select v-model="form.schedule_type"><el-option label="手动" value="manual" /><el-option label="每隔 N 分钟" value="interval" /><el-option label="每天" value="daily" /><el-option label="每周" value="weekly" /></el-select></el-form-item>
      <el-form-item v-if="form.schedule_type === 'interval'" label="间隔（分钟，15～10080）"><el-input-number v-model="form.interval_minutes" :min="15" :max="10080" /></el-form-item>
      <el-form-item v-if="['daily','weekly'].includes(form.schedule_type)" label="执行时间（所选时区）"><el-time-select v-model="form.local_time" start="00:00" step="00:01" end="23:59" /></el-form-item>
      <el-form-item v-if="form.schedule_type === 'weekly'" label="星期"><el-checkbox-group v-model="form.weekdays"><el-checkbox v-for="(day, i) in days" :key="day" :label="i + 1">{{ day }}</el-checkbox></el-checkbox-group></el-form-item>
      <el-form-item label="计划时区"><el-select v-model="form.timezone"><el-option label="北京时间 UTC+8" value="Asia/Shanghai" /><el-option label="菲律宾时间 UTC+8" value="Asia/Manila" /><el-option label="协调世界时 UTC" value="UTC" /><el-option v-if="!['Asia/Shanghai','Asia/Manila','UTC'].includes(form.timezone)" :label="form.timezone" :value="form.timezone" /></el-select></el-form-item>
      <el-form-item label="错过执行（超出计划时点 180 秒）"><el-radio-group v-model="form.catch_up"><el-radio value="skip">跳过</el-radio><el-radio value="run_once">恢复后补跑一次</el-radio></el-radio-group></el-form-item>
      <el-form-item label="单段执行预算（秒）"><el-input-number v-model="form.execution_budget_seconds" :min="0" :max="720" :step="60" :precision="0" /><p>预算到达后完成当前页并保存进度，释放执行名额后自动续跑；整次采集完成才计为成功。Shopee 订单缺失 ID 补采的 0 使用默认 240 秒预算，其他任务的 0 关闭分段。</p></el-form-item>
      <el-form-item label="暂停至（含时区，可留空）"><el-input v-model="form.pause_until" clearable placeholder="例如 2026-09-15T09:00:00+08:00" /></el-form-item>
    </el-form>
    <p>失败重试：最多 {{ job.max_retry_count ?? '—' }} 次，指数退避（基础 {{ job.backoff_base_seconds ?? '—' }} 秒）；不改变正常计划。</p>
    <p v-if="job.schedule_type === 'cron'">旧 Cron 计划不派发；请改为间隔、每日或每周后保存。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="schedule-actions"><el-button :disabled="!canManage || saving" :loading="previewing" @click="preview">预览范围与计划</el-button><el-button type="primary" :disabled="!canManage || !previewed || previewing" :loading="saving" @click="save">保存设置（不执行）</el-button></div>
    <p v-if="collectionRange">本次预览范围：{{ localDateTime(collectionRange.time_from) }} 至 {{ localDateTime(collectionRange.time_to) }}（{{ form.timezone }}；{{ syncTime(collectionRange.time_from) }} 至 {{ syncTime(collectionRange.time_to) }} UTC）。{{ sync_policy?.notice || '最近 N 天在实际执行时重新计算。' }}</p>
    <p v-else-if="previewed && sync_policy?.notice">{{ sync_policy.notice }}</p>
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
import { syncError, syncTime } from '../utils/syncPresentation';
const props = defineProps({ job: { type: Object, required: true }, canManage: Boolean });
const emit = defineEmits(['saved']);
const isProductJob = computed(() => props.job.resource_type === 'platform_product');
const supportsProductOrderBackfill = computed(() => isProductJob.value && String(props.job.platform || '').toLowerCase() === 'shopee');
const isMissingOrdersOnly = computed(() => supportsProductOrderBackfill.value && form.product_order_backfill === 'order_missing_only');
const isOrderJob = computed(() => props.job.resource_type === 'sales_order');
const supportsRange = computed(() => ['sales_order', 'refund_return', 'settlement_bill'].includes(props.job.resource_type) || (isProductJob.value && !isMissingOrdersOnly.value && form.product_full_sync === false));
const maxDays = computed(() => {
  if (isProductJob.value) return 30;
  return 31;
});
const collectionBasis = computed(() => {
  if (isProductJob.value) return '商品按平台更新时间采集。';
  if (props.job.resource_type === 'refund_return') return '退款按申请创建时间采集。';
  if (props.job.resource_type === 'settlement_bill') return '财务流水按平台账务时间采集。';
  return form.collection_time_basis === 'created' ? '订单按创建时间采集。' : '订单按更新时间采集。';
});
const collectionRange = ref(null), sync_policy = ref(null);
const form = reactive({}), times = ref([]), previewed = ref(false), previewing = ref(false), saving = ref(false), error = ref('');
const recommendation = computed(() => props.job.recommended_policy || {});
const hasRecommendation = computed(() => props.canManage && recommendation.value.available === true && recommendation.value.values && typeof recommendation.value.values === 'object');
const supportsEfficientPolicy = computed(() => ['sales_order', 'refund_return', 'settlement_bill'].includes(props.job.resource_type) || (isProductJob.value && ['shopee', 'tiktok'].includes(String(props.job.platform || '').toLowerCase())));
const canEditAnchor = computed(() => supportsEfficientPolicy.value && form.strategy_profile === 'efficient_v1' && ((isOrderJob.value && form.query_mode === 'incremental' && form.collection_time_basis === 'updated') || (isProductJob.value && !isMissingOrdersOnly.value && form.product_full_sync === false && form.query_mode === 'incremental')));
const days = ['周一','周二','周三','周四','周五','周六','周日'];
watch(() => props.job, job => { Object.assign(form, { schedule_type: job.schedule_type === 'hourly' ? 'interval' : job.schedule_type === 'cron' ? 'manual' : job.schedule_type || 'manual', interval_minutes: job.interval_minutes || 60, local_time: job.local_time || '02:00', weekdays: [...(job.weekdays || [1])], timezone: job.timezone || 'Asia/Shanghai', catch_up: job.catch_up || 'skip', pause_until: job.pause_until || '', execution_budget_seconds: job.execution_budget_seconds ?? 0, overlap_minutes: job.overlap_minutes ?? 5 }); }, { immediate: true });
watch(() => props.job, job => {
  if (supportsEfficientPolicy.value) {
    form.strategy_profile = job.strategy_profile === 'efficient_v1' ? 'efficient_v1' : 'legacy';
    if (job.strategy_profile === 'efficient_v1') form.incremental_anchor = job.incremental_anchor || 'lookback';
    else delete form.incremental_anchor;
  } else {
    delete form.strategy_profile;
    delete form.incremental_anchor;
  }
  if (job.resource_type === 'platform_product') form.product_full_sync = job.product_full_sync !== false;
  else delete form.product_full_sync;
  if (job.resource_type === 'platform_product' && String(job.platform || '').toLowerCase() === 'shopee') form.product_order_backfill = job.product_order_backfill || 'catalog_and_order_missing';
  else delete form.product_order_backfill;
  if (supportsRange.value || isProductJob.value) Object.assign(form, { query_mode: job.query_mode || 'incremental', lookback_days: job.lookback_days ?? 1, range_start_at: collectionDate(job.range_start_at), range_end_at: collectionDate(job.range_end_at) });
  else for (const key of ['query_mode', 'lookback_days', 'range_start_at', 'range_end_at']) delete form[key];
  if (job.resource_type === 'sales_order') form.collection_time_basis = job.collection_time_basis || (form.query_mode === 'range' ? 'created' : 'updated');
  else delete form.collection_time_basis;
}, { immediate: true });
watch(form, () => { previewed.value = false; times.value = []; collectionRange.value = null; });
function localTime(value) { return new Intl.DateTimeFormat('zh-CN', { timeZone: form.timezone, dateStyle: 'short', timeStyle: 'medium', hour12: false }).format(new Date(value)); }
function localDateTime(value) {
  const date = new Date(typeof value === 'number' && Math.abs(value) < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('zh-CN', { timeZone: form.timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}
function collectionDate(value) {
  if (!value || /^\d{4}-\d{2}-\d{2}$/.test(value)) return value || '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 10);
}
function applyModeDefault() {
  if (isOrderJob.value) form.collection_time_basis = form.query_mode === 'range' ? 'created' : 'updated';
}
function applyRecommendation() {
  if (!props.canManage || !hasRecommendation.value) return;
  const values = recommendation.value.values;
  const allowed = ['strategy_profile', 'incremental_anchor', 'overlap_minutes', 'execution_budget_seconds', 'query_mode', 'lookback_days', 'range_start_at', 'range_end_at', 'collection_time_basis', 'product_full_sync', 'product_order_backfill'];
  for (const key of allowed) if (Object.hasOwn(values, key)) form[key] = values[key];
  if (form.strategy_profile !== 'efficient_v1') delete form.incremental_anchor;
  if (form.strategy_profile === 'efficient_v1' && !canEditAnchor.value) form.incremental_anchor = 'lookback';
}
function buildPayload() {
  const data = { ...form };
  if (data.strategy_profile === 'efficient_v1') {
    if (!canEditAnchor.value) data.incremental_anchor = 'lookback';
  } else {
    delete data.incremental_anchor;
    delete data.overlap_minutes;
  }
  return data;
}
async function preview() {
  if (!props.canManage || previewing.value) return;
  previewing.value = true; error.value = ''; previewed.value = false;
  const data = buildPayload();
  const payload = JSON.stringify(data);
  try {
    const response = await requestApi({ method: 'post', url: `/api/internal/integrations/sync-jobs/${props.job.id}/schedule-preview/`, data: JSON.parse(payload) });
    if (!response.success) throw new Error(response.message);
    if (payload !== JSON.stringify(buildPayload())) return;
    times.value = response.data.times; collectionRange.value = response.data.collection_range; sync_policy.value = response.data.sync_policy || null; previewed.value = true;
  } catch (e) { error.value = syncError(e.message); }
  finally { previewing.value = false; }
}
async function save() {
  if (!props.canManage || !previewed.value || saving.value) return;
  saving.value = true; error.value = '';
  try {
    if (props.job.is_enabled) await ElMessageBox.confirm('任务当前已启用，新计划保存后将影响后续调度，不会立即执行。确认保存？', '确认计划变更');
    const data = buildPayload();
    const response = await updateSyncJob(props.job.id, data);
    if (!response.success) throw new Error(response.message);
    ElMessage.success('采集范围与计划已保存，未执行任务；启停状态保持不变。'); emit('saved');
  } catch (e) { if (e !== 'cancel' && e !== 'close') error.value = syncError(e.message); }
  finally { saving.value = false; }
}
</script>
<style scoped>
.schedule-settings { margin-top:20px; padding-top:16px; border-top:1px solid #dbe3ec; } h3 { margin:0; font-size:16px; } p,li { font-size:13px; line-height:1.6; color:#475569; } .el-select,.el-input { width:100%; } .schedule-actions { display:flex; gap:8px; margin:12px 0; } small { display:block; color:#64748b; }
</style>
