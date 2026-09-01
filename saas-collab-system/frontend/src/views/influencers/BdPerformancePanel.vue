<template>
  <section class="performance-panel" data-test="bd-performance-panel">
    <div class="metrics">
      <div><span>BD 成员</span><strong>{{ displayCount(totalMetric('owner_count', rows.length)) }}</strong><small>统计范围内</small></div>
      <div><span>送样记录</span><strong>{{ displayCount(totalMetric('samples', totalMetric('sample_count', 0))) }}</strong><small>已实际送样</small></div>
      <div><span>合作单 GMV</span><strong>{{ formatMoney(totalMetric('gmv', null)) }}</strong><small>{{ filters.currency }}</small></div>
      <div><span>合作单 ROI</span><strong>{{ formatRoi(totalMetric('roi', null)) }}</strong><small>GMV / 投入</small></div>
    </div>

    <el-card class="workspace-card" shadow="never">
      <div class="toolbar">
        <el-date-picker v-model="filters.startDay" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" />
        <el-date-picker v-model="filters.endDay" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" :disabled-date="isEndDateDisabled" />
        <el-select v-model="filters.currency" placeholder="金额币种">
          <el-option v-for="item in BD_PERFORMANCE_CURRENCIES" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <div class="button-group" aria-label="归属方案">
          <button type="button" :class="{ active: filters.attribution === 'strict' }" :aria-pressed="filters.attribution === 'strict'" @click="filters.attribution = 'strict'">方式一<small>达人+店铺+商品</small></button>
          <button type="button" :class="{ active: filters.attribution === 'fallback' }" :aria-pressed="filters.attribution === 'fallback'" @click="filters.attribution = 'fallback'">方式二<small>达人+店铺</small></button>
        </div>
        <div class="button-group" aria-label="指标范围">
          <button type="button" :class="{ active: filters.metrics === 'core' }" :aria-pressed="filters.metrics === 'core'" @click="filters.metrics = 'core'">核心<small>GMV/投入/ROI</small></button>
          <button type="button" :class="{ active: filters.metrics === 'full' }" :aria-pressed="filters.metrics === 'full'" @click="filters.metrics = 'full'">完整<small>全部指标</small></button>
        </div>
        <el-button type="primary" :loading="loading" @click="load">刷新统计</el-button>
        <el-button :disabled="!rows.length || loading" @click="downloadCsv">导出 CSV</el-button>
      </div>

      <div class="scope-bar">
        <span>统计范围：{{ filters.startDay }} 至 {{ filters.endDay }}</span>
        <span data-test="performance-updated">数据更新时间：{{ formatTime(lastUpdated) }}</span>
      </div>

      <el-alert v-if="errorMessage" type="error" show-icon :closable="false" :title="errorMessage">
        <template #default><el-button link type="primary" @click="load">重试</el-button></template>
      </el-alert>
      <div v-else-if="state === 'loading'" class="panel-state" data-test="performance-loading">正在加载绩效聚合数据...</div>
      <div v-else-if="state === 'empty'" class="panel-state" data-test="performance-empty">当前筛选条件下暂无绩效数据</div>
      <template v-else>
        <el-alert v-if="sourceMessage" class="source-alert" type="info" show-icon :closable="false" :title="sourceMessage" />
        <el-table v-loading="loading" :data="rows" empty-text="暂无绩效数据">
          <el-table-column prop="owner" label="BD 成员" min-width="140" />
          <el-table-column prop="task_count" label="建联任务" min-width="110" />
          <el-table-column prop="sample_count" label="送样记录" min-width="110" />
          <el-table-column prop="valid_order_count" label="有效订单" min-width="110" />
          <el-table-column prop="gmv" label="合作单 GMV" min-width="145"><template #default="{ row }">{{ formatMoney(row.gmv) }}</template></el-table-column>
          <el-table-column prop="investment" label="合作单投入" min-width="145"><template #default="{ row }">{{ formatMoney(row.investment) }}</template></el-table-column>
          <el-table-column prop="roi" label="合作单 ROI" min-width="120"><template #default="{ row }">{{ formatRoi(row.roi) }}</template></el-table-column>
          <template v-if="filters.metrics === 'full'">
            <el-table-column prop="linked_count" label="已建联" min-width="100" />
            <el-table-column prop="shipped_count" label="已送达" min-width="100" />
            <el-table-column prop="item_quantity" label="商品件数" min-width="100" />
            <el-table-column prop="commission" label="佣金" min-width="125"><template #default="{ row }">{{ formatMoney(row.commission) }}</template></el-table-column>
            <el-table-column label="视频结果" min-width="120"><template #default="{ row }">{{ formatVideo(row) }}</template></el-table-column>
          </template>
        </el-table>
      </template>
    </el-card>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { BD_PERFORMANCE_CURRENCIES, fetchBdPerformance } from '../../api/influencers';
import { collectionRows } from '../../utils/businessResponse';
import { bdPerformanceErrorMessage, calendarDayCount, defaultCompletedDateRange, isDateRangeWithinLimit } from './performanceDate';

const filters = reactive({ ...defaultCompletedDateRange(), currency: 'CNY', attribution: 'strict', metrics: 'core' });
const rows = ref([]);
const performance = ref({});
const loading = ref(false);
const state = ref('loading');
const errorMessage = ref('');

const totals = computed(() => performance.value?.totals || {});
const lastUpdated = computed(() => performance.value?.updated_at || performance.value?.data_updated_at || performance.value?.generated_at || performance.value?.data_as_of);
const sourceMessage = computed(() => ({
  not_imported: '暂无已导入的联盟订单，金额指标保持为空。',
  awaiting_fulfillment_data: '等待送样履约数据完成归属，当前不展示推算金额。',
  empty: '当前日期范围暂无可归属的绩效记录。'
}[performance.value?.source_status] || ''));

function totalMetric(name, fallback) { return totals.value[name] ?? fallback; }
function displayCount(value) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value);
}
function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? `${filters.currency} ${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : String(value);
}
function formatRoi(value) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(4)}x` : String(value);
}
function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) || /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}
function formatVideo(row) {
  const status = performance.value?.video_status || performance.value?.video?.status;
  if (performance.value?.video_available === false || ['unavailable', 'not_precomputed', 'pending'].includes(status) || !status) return '待预计算';
  return row.video_count ?? row.video_results ?? row.videos ?? '—';
}
function isEndDateDisabled(value) {
  if (!filters.startDay) return false;
  const endDay = `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  return !isDateRangeWithinLimit(filters.startDay, endDay);
}
function validateDates() {
  if (!filters.startDay || !filters.endDay) return '请选择完整日期范围';
  if (filters.startDay > filters.endDay) return '开始日期不能晚于结束日期';
  const dayCount = calendarDayCount(filters.startDay, filters.endDay);
  if (dayCount === null) return '日期格式不正确，请重新选择日期';
  if (dayCount > 31) return `统计范围最多支持 31 个自然日，当前为 ${dayCount} 天，请调整结束日期`;
  return '';
}
function clearResults() { rows.value = []; performance.value = {}; }
async function load() {
  const validationMessage = validateDates();
  if (validationMessage) { clearResults(); errorMessage.value = validationMessage; state.value = 'error'; return; }
  loading.value = true; state.value = 'loading'; errorMessage.value = '';
  try {
    const response = await fetchBdPerformance({ start_date: filters.startDay, end_date: filters.endDay, currency: filters.currency, attribution: filters.attribution, metrics: filters.metrics });
    if (!response?.success) {
      clearResults(); errorMessage.value = bdPerformanceErrorMessage(response); state.value = 'error'; return;
    }
    performance.value = response.data || {};
    rows.value = collectionRows(response.data);
    state.value = rows.value.length ? 'ready' : 'empty';
  } catch (error) {
    clearResults(); errorMessage.value = error?.message || '绩效聚合数据加载失败'; state.value = 'error';
  } finally { loading.value = false; }
}
function csvEscape(value) { return `"${String(value ?? '').replaceAll('"', '""')}"`; }
function downloadCsv() {
  if (!rows.value.length) return;
  const columns = [['BD 成员', 'owner'], ['建联任务', 'task_count'], ['送样记录', 'sample_count'], ['有效订单', 'valid_order_count'], ['合作单 GMV', 'gmv'], ['合作单投入', 'investment'], ['合作单 ROI', 'roi']];
  if (filters.metrics === 'full') columns.push(['已建联', 'linked_count'], ['已送达', 'shipped_count'], ['商品件数', 'item_quantity'], ['佣金', 'commission'], ['视频结果', 'video']);
  const lines = [
    ['统计开始日期', filters.startDay, '统计结束日期', filters.endDay, '币种', filters.currency, '归属方式', filters.attribution].map(csvEscape).join(','),
    columns.map(([label]) => csvEscape(label)).join(','),
    ...rows.value.map((row) => columns.map(([, key]) => csvEscape(key === 'video' ? formatVideo(row) : row[key])).join(','))
  ];
  const blob = new Blob([`\uFEFF${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' });
  const urlApi = globalThis.URL;
  if (!urlApi?.createObjectURL) return ElMessage.warning('当前环境不支持 CSV 下载');
  const link = document.createElement('a'); link.href = urlApi.createObjectURL(blob); link.download = `bd-performance-${filters.startDay}-${filters.endDay}.csv`; link.click(); urlApi.revokeObjectURL?.(link.href);
}
onMounted(load);
</script>

<style scoped>
.performance-panel { display: grid; gap: 14px; min-width: 0; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; border: 1px solid #dce4e9; border-radius: 9px; background: #fff; }
.metrics > div { display: grid; gap: 5px; min-height: 86px; padding: 15px 16px; border-right: 1px solid #e2e8ec; }
.metrics > div:last-child { border-right: 0; box-shadow: inset 3px 0 #14936f; }
.metrics span, .metrics small { color: #6b7b86; font-size: 12px; }
.metrics strong { color: #15232e; font-size: 24px; line-height: 1; }
.workspace-card { border-color: #dce4e9; }
.toolbar { display: flex; flex-wrap: nowrap; align-items: stretch; gap: 8px; margin-bottom: 13px; overflow-x: auto; }
.toolbar > .el-date-editor { flex: 0 0 145px; width: 145px; }
.toolbar > .el-select { flex: 0 0 145px; width: 145px; }
.toolbar > .el-button { flex: 0 0 auto; }
.button-group { display: flex; flex: 0 0 auto; overflow: hidden; border: 1px solid #d7e0e5; border-radius: 7px; background: #fff; }
.button-group button { display: grid; gap: 1px; min-width: 108px; padding: 5px 10px; border: 0; border-right: 1px solid #d7e0e5; background: #fff; color: #526570; cursor: pointer; }
.button-group button:last-child { border-right: 0; }
.button-group button small { color: #83919a; font-size: 9px; }
.button-group button.active { background: #eaf6f2; color: #087657; box-shadow: inset 0 0 0 1px #14936f; }
.scope-bar { display: flex; justify-content: space-between; gap: 12px; margin: 0 0 12px; color: #768690; font-size: 12px; }
.source-alert { margin-bottom: 12px; }
.panel-state { display: grid; min-height: 150px; place-items: center; border: 1px dashed #dce4e9; color: #768690; }
@media (max-width: 1100px) { .toolbar { flex-wrap: wrap; overflow: visible; } }
@media (max-width: 760px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metrics > div:nth-child(2) { border-right: 0; }
  .scope-bar { display: grid; }
  .toolbar > .el-date-editor, .toolbar > .el-select, .button-group { flex: 1 1 100%; width: 100%; }
  .button-group button { flex: 1; min-width: 0; }
}
</style>
