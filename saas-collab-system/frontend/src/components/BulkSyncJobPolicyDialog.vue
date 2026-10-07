<template>
  <el-dialog :model-value="modelValue" title="批量修改同步策略" width="min(760px, 94vw)" :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <p class="note">仅修改勾选的设置。请勾选同平台、同资源类型的任务；运行中或排队中的任务会跳过。</p>
    <el-form label-position="top">
      <div class="fields">
        <el-form-item label="修改项目" class="wide">
          <el-checkbox-group v-model="chosenFields">
            <el-checkbox label="重试次数" value="max_retry_count" />
            <el-checkbox label="重试间隔" value="backoff_base_seconds" />
            <el-checkbox label="每页条数" value="query_page_size" />
            <el-checkbox label="最大页数" value="max_pages" />
            <el-checkbox label="最大记录数" value="max_records" />
            <el-checkbox label="重叠分钟数" value="overlap_minutes" />
            <el-checkbox label="定时计划" value="schedule" />
            <el-checkbox label="单段执行预算" value="execution_budget_seconds" />
            <el-checkbox label="采集范围" value="query" />
            <el-checkbox v-if="jobs[0]?.resource_type === 'sales_order'" label="订单时间口径" value="collection_time_basis" />
          </el-checkbox-group>
        </el-form-item>
        <el-form-item v-if="chosenFields.includes('max_retry_count')" label="最大重试次数"><el-input-number v-model="policy.max_retry_count" :min="0" :max="10" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('backoff_base_seconds')" label="重试间隔基数（秒）"><el-input-number v-model="policy.backoff_base_seconds" :min="1" :max="5" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('query_page_size')" label="每页条数"><el-input-number v-model="policy.query_page_size" :min="1" :max="100" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('max_pages')" label="单次最大页数"><el-input-number v-model="policy.max_pages" :min="1" :max="1000" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('max_records')" label="单次最大记录数"><el-input-number v-model="policy.max_records" :min="1" :max="100000" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('overlap_minutes')" label="重叠查询分钟数"><el-input-number v-model="policy.overlap_minutes" :min="0" :max="1440" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('execution_budget_seconds')" label="单段预算（秒）"><el-input-number v-model="policy.execution_budget_seconds" :min="60" :max="720" :step="60" :precision="0" /></el-form-item>
        <el-form-item v-if="chosenFields.includes('collection_time_basis')" label="订单时间口径"><el-select v-model="policy.collection_time_basis"><el-option label="创建时间" value="created" /><el-option label="更新时间" value="updated" /></el-select></el-form-item>
        <template v-if="chosenFields.includes('schedule')">
          <el-form-item label="调度方式"><el-select v-model="policy.schedule_type"><el-option label="手动" value="manual" /><el-option label="每小时" value="hourly" /><el-option label="固定间隔" value="interval" /><el-option label="每日" value="daily" /><el-option label="每周" value="weekly" /></el-select></el-form-item>
          <el-form-item v-if="policy.schedule_type === 'interval'" label="间隔分钟"><el-input-number v-model="policy.interval_minutes" :min="15" :max="10080" /></el-form-item>
          <el-form-item v-if="['daily', 'weekly'].includes(policy.schedule_type)" label="执行时间"><el-time-picker v-model="policy.local_time" value-format="HH:mm" format="HH:mm" /></el-form-item>
          <el-form-item v-if="policy.schedule_type === 'weekly'" label="每周执行日" class="wide"><el-checkbox-group v-model="policy.weekdays"><el-checkbox-button v-for="day in weekdayOptions" :key="day.value" :value="day.value">{{ day.label }}</el-checkbox-button></el-checkbox-group></el-form-item>
          <el-form-item label="执行时区"><el-input v-model="policy.timezone" /></el-form-item>
          <el-form-item label="漏跑策略"><el-select v-model="policy.catch_up"><el-option label="跳过" value="skip" /><el-option label="补跑一次" value="run_once" /></el-select></el-form-item>
        </template>
        <template v-if="chosenFields.includes('query')">
          <el-form-item label="采集方式"><el-select v-model="policy.query_mode"><el-option label="按进度增量" value="incremental" /><el-option label="指定时间范围" value="range" /></el-select></el-form-item>
          <el-form-item v-if="policy.query_mode === 'incremental'" label="首次回看天数"><el-input-number v-model="policy.lookback_days" :min="1" :max="3650" /></el-form-item>
          <el-form-item v-if="policy.query_mode === 'range'" label="开始日期（北京时间）"><el-date-picker v-model="policy.range_start_at" type="date" value-format="YYYY-MM-DD" /></el-form-item>
          <el-form-item v-if="policy.query_mode === 'range'" label="结束日期（北京时间，含当天）"><el-date-picker v-model="policy.range_end_at" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        </template>
      </div>
    </el-form>
    <el-alert v-if="chosenFields.includes('query')" title="修改采集范围会按现有规则重置同步游标；历史数据和运行记录保留。" type="warning" :closable="false" show-icon />
    <p>预览：可修改 {{ preview.eligible.length }} 个，跳过 {{ preview.skipped.length }} 个。</p>
    <p v-if="chosenFields.length" class="note">将修改：{{ changeSummary }}</p>
    <ul v-if="preview.skipped.length" class="result-list"><li v-for="item in preview.skipped" :key="item.id">任务 #{{ item.id }}：{{ item.reason }}</li></ul>
    <el-alert v-if="outcome" :title="outcome.summary" type="info" :closable="false" show-icon />
    <ul v-if="outcome?.failed.length" class="result-list"><li v-for="item in outcome.failed" :key="item.id">任务 #{{ item.id }}：{{ item.reason }}</li></ul>
    <template #footer><el-button @click="emit('update:modelValue', false)">关闭</el-button><el-button type="primary" :loading="saving" :disabled="!chosenFields.length || !preview.eligible.length || !!outcome" @click="save">确认批量修改</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { updateSyncJob } from '../api/integrations';
import { buildBulkSyncJobPayload, classifyBulkSyncJobs } from '../utils/bulkSyncJobPolicy';

const props = defineProps({ modelValue: Boolean, jobs: { type: Array, default: () => [] } });
const emit = defineEmits(['update:modelValue', 'saved']);
const chosenFields = ref([]);
const saving = ref(false);
const outcome = ref(null);
const policy = reactive({
  max_retry_count: 3, backoff_base_seconds: 1, query_page_size: 50, max_pages: 100, max_records: 50000,
  overlap_minutes: 5, collection_time_basis: 'created', schedule_type: 'manual', interval_minutes: 60,
  execution_budget_seconds: 300,
  local_time: '02:00', weekdays: [1, 2, 3, 4, 5, 6, 7], timezone: 'Asia/Shanghai', catch_up: 'skip',
  query_mode: 'incremental', lookback_days: 30, range_start_at: null, range_end_at: null,
});
const weekdayOptions = [{ label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 }, { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 7 }];
const preview = computed(() => classifyBulkSyncJobs(props.jobs));
const payload = computed(() => buildBulkSyncJobPayload(chosenFields.value, policy));
const changeSummary = computed(() => Object.entries(payload.value).map(([key, value]) => `${key} = ${Array.isArray(value) ? value.join(',') : value}`).join('；'));
watch(() => props.modelValue, open => { if (open) { chosenFields.value = []; outcome.value = null; } });

async function save() {
  if (saving.value || outcome.value || !chosenFields.value.length || !preview.value.eligible.length) return;
  const update = payload.value;
  if (chosenFields.value.includes('schedule') && (!update.timezone?.trim()
    || (['daily', 'weekly'].includes(update.schedule_type) && !update.local_time)
    || (update.schedule_type === 'weekly' && !update.weekdays.length))) {
    ElMessage.warning('请填写完整的定时计划。'); return;
  }
  if (update.query_mode === 'range' && (!update.range_start_at || !update.range_end_at || update.range_start_at > update.range_end_at)) {
    ElMessage.warning('请填写有效的采集开始和结束时间。'); return;
  }
  if (chosenFields.value.includes('query')) {
    try { await ElMessageBox.confirm('采集范围变化可能重置所选任务的同步游标。确认继续？', '确认批量修改', { type: 'warning' }); }
    catch (reason) { if (reason === 'cancel' || reason === 'close') return; throw reason; }
  }
  saving.value = true;
  const failed = [...preview.value.skipped];
  let succeeded = 0;
  try {
    for (const row of preview.value.eligible) {
      try {
        const response = await updateSyncJob(row.id, update);
        if (response?.success) succeeded += 1;
        else failed.push({ id: row.id, reason: response?.message || '保存失败' });
      } catch (error) { failed.push({ id: row.id, reason: error?.message || '保存失败' }); }
    }
    outcome.value = { summary: `成功 ${succeeded} 个，跳过或失败 ${failed.length} 个。`, failed };
    ElMessage[failed.length ? 'warning' : 'success'](outcome.value.summary);
    emit('saved');
  } finally { saving.value = false; }
}
</script>

<style scoped>
.note { color: #607087; font-size: 12px; line-height: 1.7; }
.fields { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.fields .wide { grid-column: 1 / -1; }
.fields :deep(.el-select), .fields :deep(.el-date-editor), .fields :deep(.el-input-number) { width: 100%; }
.result-list { max-height: 120px; overflow: auto; padding-left: 22px; color: #9a3412; font-size: 12px; }
@media (max-width: 760px) { .fields { grid-template-columns: 1fr; } }
</style>
