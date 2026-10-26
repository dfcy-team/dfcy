<template>
  <section class="performance-panel" data-test="bd-performance-panel">
    <div class="metrics">
      <div><span>BD 成员</span><strong>{{ displayCount(totalMetric('owner_count', rows.length)) }}</strong><small>统计范围内</small></div>
      <div><span>送样记录</span><strong>{{ displayCount(totalMetric('samples', totalMetric('sample_count', 0))) }}</strong><small>已实际送样</small></div>
      <div><span>合作预估计佣金额</span><strong>{{ formatMoney(totalMetric('gmv', null)) }}</strong><small>{{ reportCurrency }}</small></div>
      <div><span>合作单 ROI</span><strong>{{ formatRoi(totalMetric('roi', null)) }}</strong><small>预估计佣金额 / 总成本</small></div>
    </div>

    <el-card class="workspace-card" shadow="never">
      <div class="toolbar">
        <div class="date-filter"><el-date-picker v-model="filters.startDay" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" /></div>
        <div class="date-filter"><el-date-picker v-model="filters.endDay" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" /></div>
        <el-select v-model="filters.currency" placeholder="金额币种">
          <el-option v-for="item in BD_PERFORMANCE_CURRENCIES" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <div class="button-group" aria-label="归属方案">
          <button type="button" :class="{ active: filters.attribution === 'strict' }" :aria-pressed="filters.attribution === 'strict'" @click="filters.attribution = 'strict'">方式一<small>达人+店铺+商品</small></button>
          <button type="button" :class="{ active: filters.attribution === 'fallback' }" :aria-pressed="filters.attribution === 'fallback'" @click="filters.attribution = 'fallback'">方式二<small>达人+店铺</small></button>
        </div>
        <div class="button-group" aria-label="指标范围">
          <button type="button" :class="{ active: filters.metrics === 'core' }" :aria-pressed="filters.metrics === 'core'" @click="filters.metrics = 'core'">核心<small>计佣金额/投入/ROI</small></button>
          <button type="button" :class="{ active: filters.metrics === 'full' }" :aria-pressed="filters.metrics === 'full'" @click="filters.metrics = 'full'">完整<small>全部指标</small></button>
        </div>
        <el-button type="primary" :loading="loading" @click="loadSelectedRange">刷新统计</el-button>
        <el-button :disabled="!rows.length || loading" @click="downloadCsv">导出 CSV</el-button>
      </div>

      <div class="scope-bar">
        <span>统计范围：{{ filters.startDay && filters.endDay ? `${filters.startDay} 至 ${filters.endDay}` : '正在确定默认范围…' }}</span>
        <span data-test="performance-updated">联盟订单数据截至：{{ formatTime(lastUpdated) }}</span>
      </div>
      <el-alert v-if="!errorMessage && !defaultRangePending && state !== 'loading' && rangeSource === 'default'" class="source-alert" type="info" show-icon :closable="false" title="默认日期范围按联盟订单最新业务日期计算。" />
      <el-alert v-else-if="!errorMessage && state !== 'loading' && rangeSource === 'selected'" class="source-alert" type="info" show-icon :closable="false" title="当前统计按所选日期范围查询。" />

      <el-alert v-if="errorMessage" type="error" show-icon :closable="false" :title="errorMessage">
        <template #default><el-button link type="primary" @click="retryLoad">重试</el-button></template>
      </el-alert>
      <div v-else-if="state === 'loading'" class="panel-state" data-test="performance-loading">{{ defaultRangePending ? '正在确定默认日期范围并加载绩效聚合数据…' : '正在加载绩效聚合数据...' }}</div>
      <div v-else-if="state === 'empty'" class="panel-state" data-test="performance-empty">当前筛选条件下暂无绩效数据</div>
      <template v-else>
        <el-alert class="source-alert" type="info" show-icon :closable="false" title="金额口径：预估计佣金额，不使用支付金额或预估佣金。" />
        <el-alert class="source-alert" type="info" show-icon :closable="false" title="总成本 = 本期送样成本 + 已归因有效订单的实际标准佣金 + 实际广告佣金。佣金不乘数量；缺失不按零处理，不用预估佣金替代。" />
        <div class="cost-summary" data-test="bd-cost-summary">
          <div v-for="column in BD_COST_COLUMNS" :key="column.key">
            <span>{{ column.label }}</span><strong>{{ costDisplay(totals, column, formatMoney) }}</strong>
          </div>
        </div>
        <el-alert v-if="amountWarning" class="source-alert" type="warning" show-icon :closable="false" :title="amountWarning" />
        <el-alert v-if="sourceMessage" class="source-alert" type="info" show-icon :closable="false" :title="sourceMessage" />
        <el-table ref="performanceTable" v-loading="loading" :data="rows" empty-text="暂无绩效数据">
          <el-table-column type="expand" width="52">
            <template #default="{ row }">
              <div class="country-breakdown">
                <p>仅展示已归因到该 BD 送样记录的联盟订单；本币预估计佣金额不跨国家相加。</p>
                <el-table :data="row.country_breakdown || []" size="small" border>
                  <el-table-column prop="country" label="国家" min-width="120" />
                  <el-table-column prop="currency" label="本币" min-width="100" />
                  <el-table-column prop="sample_count" label="对应送样" min-width="120" />
                  <el-table-column prop="shipped_count" label="已发货送样" min-width="130" />
                  <el-table-column prop="valid_order_count" label="有效订单" min-width="120" />
                  <el-table-column prop="gmv" label="本币预估计佣金额" min-width="180">
                    <template #default="{ row: country }">{{ formatNativeMoney(country.gmv, country.currency) }}</template>
                  </el-table-column>
                </el-table>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="币种明细" width="105">
            <template #default="{ row }">
              <el-button link type="primary" @click="toggleCountry(row)">查看明细</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="owner" label="BD 成员" min-width="140" />
          <el-table-column prop="sample_count" label="送样记录" min-width="110" />
          <el-table-column prop="valid_order_count" label="有效订单" min-width="110" />
          <el-table-column prop="gmv" label="合作预估计佣金额" min-width="185"><template #default="{ row }">{{ formatMoney(row.gmv) }}</template></el-table-column>
          <el-table-column prop="gmv_php" label="PHP 预估计佣金额" min-width="175"><template #default="{ row }">{{ formatNativeMoney(row.gmv_php, 'PHP') }}</template></el-table-column>
          <el-table-column prop="gmv_myr" label="MYR 预估计佣金额" min-width="175"><template #default="{ row }">{{ formatNativeMoney(row.gmv_myr, 'MYR') }}</template></el-table-column>
          <el-table-column prop="gmv_thb" label="THB 预估计佣金额" min-width="175"><template #default="{ row }">{{ formatNativeMoney(row.gmv_thb, 'THB') }}</template></el-table-column>
          <el-table-column v-for="column in BD_COST_COLUMNS" :key="column.key" :prop="column.key" :label="column.label" min-width="190">
            <template #default="{ row }">{{ costDisplay(row, column, formatMoney) }}</template>
          </el-table-column>
          <el-table-column prop="roi" label="合作单 ROI" min-width="120"><template #default="{ row }">{{ formatRoi(row.roi) }}</template></el-table-column>
          <template v-if="filters.metrics === 'full'">
            <el-table-column prop="shipped_count" label="已送达" min-width="100" />
            <el-table-column prop="item_quantity" label="商品件数" min-width="100" />
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
import { BD_PERFORMANCE_CURRENCIES, fetchBdPerformance, formatInfluencerError } from '../../api/influencers';
import { collectionRows } from '../../utils/businessResponse';
import { BD_COST_BASIS, BD_COST_COLUMNS, costCsvColumns, costDisplay } from '../../utils/bdPerformanceCosts';

const filters = reactive({ startDay: '', endDay: '', currency: 'CNY', attribution: 'strict', metrics: 'core' });
const rows = ref([]);
const performanceTable = ref();
const performance = ref({});
const loading = ref(false);
const state = ref('loading');
const errorMessage = ref('');
const defaultRangePending = ref(true);
const rangeSource = ref('default');

const totals = computed(() => performance.value?.totals || {});
const reportCurrency = computed(() => performance.value?.currency || filters.currency);
const amountWarning = computed(() => {
  const missingBase = Number(totals.value.missing_estimated_commission_base_count || 0);
  const missingCost = Number(totals.value.missing_cost_count || 0);
  const missingStandard = Number(totals.value.missing_actual_standard_commission_count || 0);
  const missingAds = Number(totals.value.missing_actual_ads_commission_count || 0);
  const warnings = [];
  if (missingBase) warnings.push(`${missingBase} 条订单明细缺少预估计佣金额，受影响金额和 ROI 显示为空，不使用支付金额替代`);
  if (missingCost) warnings.push(`${missingCost} 条送样记录缺少成本`);
  if (missingStandard) warnings.push(`${missingStandard} 条有效订单明细缺少实际标准佣金`);
  if (missingAds) warnings.push(`${missingAds} 条有效订单明细缺少实际广告佣金`);
  if (missingCost || missingStandard || missingAds) warnings.push('已知小计不是完整总成本，受影响总成本和 ROI 显示为空');
  if (performance.value.rate_missing) warnings.push('存在缺失汇率，受影响金额和 ROI 显示为空');
  return warnings.join('；');
});
const lastUpdated = computed(() => performance.value?.data_updated_at || performance.value?.data_as_of);
const sourceMessage = computed(() => ({
  not_imported: '暂无已导入的联盟订单，金额指标保持为空。',
  awaiting_fulfillment_data: '等待送样履约数据完成归属，当前不展示推算金额。',
  incomplete: '订单结算或退款状态尚未完整核验，仅展示已核验有效明细的已知小计，完整金额、总成本和 ROI 保持为空。',
  empty: '当前日期范围暂无可归属的绩效记录。'
}[performance.value?.source_status] || ''));

function toggleCountry(row) {
  performanceTable.value?.toggleRowExpansion(row);
}

function totalMetric(name, fallback) { return totals.value[name] ?? fallback; }
function displayCount(value) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value);
}
function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? `${reportCurrency.value} ${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : String(value);
}
function formatNativeMoney(value, currency) {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? `${currency} ${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : String(value);
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
function validateDates() {
  if (!filters.startDay || !filters.endDay) return '请选择完整日期范围';
  if (filters.startDay > filters.endDay) return '开始日期不能晚于结束日期';
  return '';
}
async function load({ includeDateRange = true } = {}) {
  if (loading.value) return;
  if (includeDateRange) {
    const validationMessage = validateDates();
    if (validationMessage) { errorMessage.value = validationMessage; state.value = 'error'; return; }
  }
  loading.value = true; state.value = 'loading'; errorMessage.value = '';
  try {
    const params = includeDateRange
      ? { currency: filters.currency, attribution: filters.attribution, metrics: filters.metrics, start_date: filters.startDay, end_date: filters.endDay }
      : {};
    const response = await fetchBdPerformance(params);
    if (!response?.success) {
      rows.value = []; performance.value = {}; errorMessage.value = formatInfluencerError(response, '绩效聚合数据加载失败'); state.value = 'error'; return;
    }
    if (response.data?.amount_basis !== 'estimated_commission_base') {
      rows.value = []; performance.value = {}; errorMessage.value = '后端金额口径尚未更新为预估计佣金额，请同步更新后端后重试。'; state.value = 'error'; return;
    }
    if (response.data?.cost_basis !== BD_COST_BASIS) {
      rows.value = []; performance.value = {}; errorMessage.value = '后端成本口径尚未更新为送样成本加两项实际佣金，请同步更新后端后重试。'; state.value = 'error'; return;
    }
    performance.value = response.data || {};
    const reportSettings = performance.value.settings || {};
    filters.currency = performance.value.currency || reportSettings.default_currency || filters.currency;
    filters.attribution = performance.value.attribution || reportSettings.default_attribution || filters.attribution;
    filters.metrics = reportSettings.default_metrics || filters.metrics;
    if (performance.value.start_date) filters.startDay = performance.value.start_date;
    if (performance.value.end_date) filters.endDay = performance.value.end_date;
    defaultRangePending.value = false;
    rows.value = collectionRows(response.data);
    state.value = rows.value.length ? 'ready' : 'empty';
  } catch (error) {
    rows.value = []; performance.value = {}; errorMessage.value = formatInfluencerError({ message: error?.message }, '绩效聚合数据加载失败'); state.value = 'error';
  } finally { loading.value = false; }
}
function loadSelectedRange() {
  if (loading.value) return;
  rangeSource.value = 'selected';
  return load({ includeDateRange: true });
}
function retryLoad() {
  return load({ includeDateRange: rangeSource.value === 'selected' });
}
function csvEscape(value) {
  const text = String(value ?? '');
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safe.replaceAll('"', '""')}"`;
}
function downloadCsv() {
  if (!rows.value.length) return;
  const startDay = performance.value.start_date || filters.startDay;
  const endDay = performance.value.end_date || filters.endDay;
  const attribution = performance.value.attribution || filters.attribution;
  const columns = [['BD 成员', 'owner'], ['送样记录', 'sample_count'], ['有效订单', 'valid_order_count'], ['合作预估计佣金额', 'gmv'], ['PH 预估计佣金额 (PHP)', 'gmv_php'], ['MY 预估计佣金额 (MYR)', 'gmv_myr'], ['TH 预估计佣金额 (THB)', 'gmv_thb'], ...costCsvColumns(), ['合作单 ROI', 'roi'], ['缺少预估计佣金额明细', 'missing_estimated_commission_base_count'], ['缺少成本送样', 'missing_cost_count'], ['缺少实际标准佣金明细', 'missing_actual_standard_commission_count'], ['缺少实际广告佣金明细', 'missing_actual_ads_commission_count']];
  if (filters.metrics === 'full') columns.push(['已送达', 'shipped_count'], ['商品件数', 'item_quantity'], ['视频结果', 'video']);
  const lines = [
    ['统计开始日期', startDay, '统计结束日期', endDay, '币种', reportCurrency.value, '归属方式', attribution, '金额口径', 'estimated_commission_base', '成本口径', BD_COST_BASIS].map(csvEscape).join(','),
    columns.map(([label]) => csvEscape(label)).join(','),
    ...rows.value.map((row) => columns.map(([, key]) => csvEscape(key === 'video' ? formatVideo(row) : row[key])).join(',')),
    columns.map(([, key]) => csvEscape(key === 'owner' ? '合计' : totals.value[key])).join(',')
  ];
  const blob = new Blob([`\uFEFF${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' });
  const urlApi = globalThis.URL;
  if (!urlApi?.createObjectURL) return ElMessage.warning('当前环境不支持 CSV 下载');
  const link = document.createElement('a'); link.href = urlApi.createObjectURL(blob); link.download = `bd-performance-${startDay}-${endDay}.csv`; link.click(); urlApi.revokeObjectURL?.(link.href);
}
onMounted(() => load({ includeDateRange: false }));
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
.date-filter { flex: 0 0 145px; width: 145px; min-width: 0; }
.date-filter :deep(.el-date-editor) { width: 100%; }
.toolbar > .el-select { flex: 0 0 145px; width: 145px; }
.toolbar > .el-button { flex: 0 0 auto; }
.button-group { display: flex; flex: 0 0 auto; overflow: hidden; border: 1px solid #d7e0e5; border-radius: 7px; background: #fff; }
.button-group button { display: grid; gap: 1px; min-width: 108px; padding: 5px 10px; border: 0; border-right: 1px solid #d7e0e5; background: #fff; color: #526570; cursor: pointer; }
.button-group button:last-child { border-right: 0; }
.button-group button small { color: #83919a; font-size: 9px; }
.button-group button.active { background: #eaf6f2; color: #087657; box-shadow: inset 0 0 0 1px #14936f; }
.scope-bar { display: flex; justify-content: space-between; gap: 12px; margin: 0 0 12px; color: #768690; font-size: 12px; }
.source-alert { margin-bottom: 12px; }
.cost-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; padding: 14px; margin-bottom: 12px; border: 1px solid #dce4e9; border-radius: 7px; background: #f7faf9; }
.cost-summary > div { display: grid; gap: 6px; min-width: 0; }
.cost-summary span { color: #6b7b86; font-size: 12px; }
.cost-summary strong { color: #15232e; font-size: 14px; overflow-wrap: anywhere; }
.country-breakdown { padding: 8px 18px 16px 52px; background: #f7faf9; }
.country-breakdown p { margin: 0 0 8px; color: #6b7b86; font-size: 12px; }
.panel-state { display: grid; min-height: 150px; place-items: center; border: 1px dashed #dce4e9; color: #768690; }
@media (max-width: 1100px) { .toolbar { flex-wrap: wrap; overflow: visible; } }
@media (max-width: 760px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cost-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metrics > div:nth-child(2) { border-right: 0; }
  .scope-bar { display: grid; }
  .date-filter, .toolbar > .el-select, .button-group { flex: 1 1 100%; width: 100%; }
  .button-group button { flex: 1; min-width: 0; }
}
</style>
