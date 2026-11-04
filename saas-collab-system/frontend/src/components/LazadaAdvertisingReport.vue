<template>
  <section class="lazada-ads-report">
    <h1>Lazada Sponsored Max 广告</h1>
    <p>查询已存报表；只有点击“采集所选店铺”才会调用平台。始终使用现有令牌，不刷新授权。</p>
    <el-alert type="info" :closable="false" title="广告报表花费不等于财务账单扣费，不自动登记财务成本。按店铺和币种分别展示；缺失日期不视为零。" />
    <el-form inline class="filters" @submit.prevent="search">
      <el-form-item label="店铺">
        <el-select v-model="storeId" clearable placeholder="全部可见店铺" :disabled="syncing">
          <el-option v-for="store in stores" :key="store.store_id" :value="store.store_id" :label="`${store.store__code} · ${store.store__name}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="报表日期（店铺站点）">
        <el-date-picker v-model="period" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" :disabled="syncing" />
      </el-form-item>
      <el-form-item><el-button type="primary" :loading="loading" :disabled="syncing" @click="search">查询已存数据</el-button></el-form-item>
      <el-form-item v-if="authorizationId"><el-button :loading="syncing" :disabled="loading || !validPeriod" @click="sync">采集所选店铺</el-button></el-form-item>
    </el-form>
    <p>单次 1～31 天；采集仅支持已结束日期。重复采集更新原日报，不重复累加。</p>
    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <el-alert v-if="message" type="success" :closable="false" :title="message" />
    <el-skeleton v-if="loading" :rows="5" animated />
    <template v-else-if="report && !error">
      <el-table v-if="report.summaries.length" :data="report.summaries" stripe border>
        <el-table-column prop="store__name" label="店铺" min-width="160" />
        <el-table-column prop="currency" label="币种" width="80" />
        <el-table-column label="已存日报花费" min-width="140"><template #default="{ row }">{{ money(row.spend) }}</template></el-table-column>
        <el-table-column label="日期覆盖" min-width="160"><template #default="{ row }">{{ row.days }}/{{ row.expected_days }} 天 · {{ row.complete ? '完整' : '不完整，非全期合计' }}</template></el-table-column>
        <el-table-column v-for="column in overviewColumns" :key="column.key" :label="column.label" min-width="150">
          <template #default="{ row }">{{ row.overview_metrics[column.key] ?? '—' }}</template>
        </el-table-column>
      </el-table>
      <p v-if="report.summaries.length">曝光、点击、收入和 ROI 仅展示同一完整采集区间的原生汇总，不将其分摊成日报；API revenue 尚未认定等于后台 Guided GMV。</p>
      <el-empty v-if="!report.results.length" description="暂无该范围的已存广告日报。请选择有查询权限的店铺并手动采集；不会自动刷新授权或生成模拟数据。" />
      <el-table v-else :data="report.results" stripe border>
        <el-table-column prop="store_name" label="店铺" min-width="160" />
        <el-table-column prop="report_date" label="报表日期" width="120" />
        <el-table-column prop="currency" label="币种" width="80" />
        <el-table-column label="报表花费"><template #default="{ row }">{{ money(row.spend) }}</template></el-table-column>
        <el-table-column prop="report_timezone" label="站点时区" min-width="160" />
        <el-table-column prop="source_snapshot_id" label="日报来源快照" min-width="120" />
        <el-table-column prop="overview_snapshot_id" label="核对汇总快照" min-width="120" />
      </el-table>
      <el-pagination v-if="report.count" :current-page="page" :page-size="20" :total="report.count" layout="total, prev, pager, next" @current-change="load" />
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessageBox } from 'element-plus';
import { fetchLazadaAdvertising } from '../api/advertising';
import { executeLazadaRead } from '../api/integrations';

const lastMonthEnd = new Date();
lastMonthEnd.setUTCDate(0);
const month = lastMonthEnd.toISOString().slice(0, 7);
const period = ref([`${month}-01`, lastMonthEnd.toISOString().slice(0, 10)]);
const storeId = ref(null), stores = ref([]), page = ref(1), report = ref(null);
const loading = ref(false), syncing = ref(false), error = ref(''), message = ref('');
const overviewColumns = [
  { key: 'impressions', label: '期间曝光' }, { key: 'clicks', label: '期间点击' },
  { key: 'revenue', label: '期间 API revenue' }, { key: 'roi', label: '期间 API ROI' }
];
const authorizationId = computed(() => stores.value.find(store => store.store_id === storeId.value)?.authorization_id);
const validPeriod = computed(() => {
  if (!Array.isArray(period.value) || period.value.length !== 2) return false;
  const days = (Date.parse(period.value[1]) - Date.parse(period.value[0])) / 86400000;
  return Number.isFinite(days) && days >= 0 && days < 31;
});
const money = value => value == null ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
let generation = 0;
function invalidate() { generation++; report.value = null; error.value = ''; message.value = ''; loading.value = false; }
watch([storeId, period], invalidate, { flush: 'sync' });
onBeforeUnmount(invalidate);
async function load(nextPage = 1) {
  const epoch = ++generation;
  report.value = null; error.value = '';
  if (!validPeriod.value) { error.value = '请选择连续 1～31 天的日期范围。'; return; }
  loading.value = true;
  try {
    const response = await fetchLazadaAdvertising({ period_start: period.value[0], period_end: period.value[1],
      ...(storeId.value ? { store_id: storeId.value } : {}), page: nextPage, page_size: 20 });
    if (epoch !== generation) return;
    if (!response.success) throw new Error(response.message || '广告数据查询失败');
    report.value = response.data; stores.value = response.data.stores; page.value = nextPage;
  } catch (cause) {
    if (epoch === generation) error.value = cause?.response?.data?.message || cause.message || '广告数据查询失败';
  } finally { if (epoch === generation) loading.value = false; }
}
function search() { message.value = ''; return load(1); }
async function sync() {
  if (syncing.value || loading.value || !authorizationId.value || !validPeriod.value) return;
  const id = authorizationId.value, dates = [...period.value], epoch = generation;
  syncing.value = true; error.value = ''; message.value = '';
  try {
    await ElMessageBox.confirm(`采集所选店铺 ${dates[0]} 至 ${dates[1]} 的 Sponsored Max 报表？不刷新授权，不修改广告或预算。`, '确认只读采集', { type: 'info' });
    if (epoch !== generation) return;
    const response = await executeLazadaRead(id, { operation: 'smax_sync', payload: { startDate: dates[0], endDate: dates[1] } });
    if (epoch !== generation) return;
    if (!response.success || response.data?.status !== 'succeeded') throw new Error(response.message || '广告采集失败');
    const success = `已核对并保存 ${response.data.days} 天；每日合计 ${response.data.daily_sum} ${response.data.currency}，未刷新授权。`;
    await load(1);
    if (!error.value) message.value = success;
  } catch (cause) {
    if (epoch === generation && cause !== 'cancel' && cause !== 'close') error.value = cause?.response?.data?.message || cause.message || '广告采集失败；系统不会刷新授权。';
  } finally { syncing.value = false; }
}
onMounted(() => load(1));
</script>

<style scoped>
.lazada-ads-report { padding: 20px; }
h1 { margin-top: 0; }
p { color: var(--el-text-color-secondary); line-height: 1.7; }
.filters { margin-top: 20px; }
.el-select { width: 240px; }
.el-pagination { margin-top: 16px; }
@media (max-width: 700px) {
  .lazada-ads-report { padding: 12px; }
  .filters :deep(.el-form-item) { display: flex; margin-right: 0; }
  .filters :deep(.el-date-editor) { width: 100%; }
}
</style>
