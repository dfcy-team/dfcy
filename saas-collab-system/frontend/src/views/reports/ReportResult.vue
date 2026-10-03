<template>
  <div class="report-result">
    <template v-if="chart === 'card'">
      <p class="result-note">各分组分别显示，不跨币种或跨 SKU 合计。</p>
      <div class="metric-cards"><button v-for="(row, index) in pageRows" :key="index" type="button" @click="select(row)">
        <span>{{ config.dimensions.map(key => dimensionValue(row[key], key)).join(' · ') }}</span>
        <strong>{{ format(row[metric], metric) }}</strong><small>{{ label(metric) }}</small>
      </button></div>
    </template>
    <template v-else-if="chart === 'pivot' && matrix.columns.length">
      <p class="result-note">缺失单元格不补零；点击单元格可{{ interaction === 'select' ? '联动其他组件' : '穿透明细' }}。</p>
      <div class="matrix-scroll"><table class="pivot-table"><thead><tr><th>分组</th><th v-for="column in matrixColumns" :key="column.key">{{ column.label }}</th></tr></thead>
        <tbody><tr v-for="row in matrixPageRows" :key="row.id"><th>{{ row.label }}</th><td v-for="column in matrixColumns" :key="column.key">
          <button v-if="row.cells[column.key]" type="button" @click="select(row.cells[column.key].source)">{{ format(row.cells[column.key].value, metric) }}</button><span v-else>—</span>
        </td></tr></tbody></table></div>
      <div v-if="matrix.rows.length > 25 || matrix.columns.length > 12" class="result-pages">
        <span>每页最多 25 行、12 列，翻页不重新读取数据。</span>
        <el-pagination v-if="matrix.rows.length > 25" v-model:current-page="matrixRowPage" :page-size="25" :total="matrix.rows.length" layout="prev, pager, next" aria-label="透视表行分页" />
        <el-pagination v-if="matrix.columns.length > 12" v-model:current-page="matrixColumnPage" :page-size="12" :total="matrix.columns.length" layout="prev, pager, next" aria-label="透视表列分页" />
      </div>
    </template>
    <template v-else-if="['bar', 'line'].includes(chart)">
      <p class="result-note">前 40 个分组 · {{ label(metric) }} · 保留币种标签，缺失值不绘制</p>
      <svg v-if="result.rows.length" class="report-chart" viewBox="0 0 900 280" role="img" :aria-label="label(metric)">
        <line x1="45" y1="230" x2="890" y2="230" stroke="#cbd5e1" />
        <polyline v-for="(series, index) in chart === 'line' ? chartModel.series : []" :key="index"
          :points="series.map(point => `${point.x},${point.y}`).join(' ')" fill="none" stroke="#5941c6" stroke-width="2" />
        <g v-for="(point, index) in chartModel.points" :key="index" class="chart-point" role="button" tabindex="0"
          :aria-label="`${point.label}：${format(point.value, metric)}`" @click="select(point.row)" @keydown.enter.prevent="select(point.row)" @keydown.space.prevent="select(point.row)">
          <rect :x="point.x - 14" y="15" width="28" height="220" fill="transparent" aria-hidden="true" />
          <rect v-if="chart === 'bar'" :x="point.x - 9" :y="Math.min(point.y, 140)" width="18" :height="Math.max(2, Math.abs(140 - point.y))" fill="#6952d9" />
          <circle v-else :cx="point.x" :cy="point.y" r="5" fill="#5941c6" />
          <title>{{ point.label }}：{{ format(point.value, metric) }}</title>
          <text v-if="chartModel.points.length <= 12" :x="point.x" :y="Math.max(20, point.y - 10)" text-anchor="middle" class="point-value">{{ format(point.value, metric) }}</text>
          <text v-if="index % Math.ceil(chartModel.points.length / 8) === 0" :x="point.x" y="252" text-anchor="middle" font-size="10">{{ index + 1 }}</text>
        </g>
        <line x1="45" y1="140" x2="890" y2="140" stroke="#94a3b8" stroke-dasharray="3 3" /><text x="8" y="144" font-size="11">0</text>
      </svg>
      <div class="chart-legend" aria-label="图表分组与数值"><button v-for="(point, index) in chartModel.points" :key="point.index" type="button" @click="select(point.row)"><span>{{ index + 1 }} · {{ point.label }}</span><strong>{{ format(point.value, metric) }}</strong></button></div>
    </template>
    <el-table v-if="showTable || chart === 'table'" :data="pageRows" stripe :max-height="maxHeight" @row-click="select">
      <el-table-column v-if="canInvestigate" label="核查" width="120"><template #default="{ row }"><el-button text type="primary" @click.stop="$emit('investigate', row)">发起核查</el-button></template></el-table-column>
      <el-table-column v-for="column in result.columns" :key="column.key" :prop="column.key" :label="column.label" :align="dataset.metrics.some(item => item.key === column.key) ? 'right' : 'left'" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ format(row[column.key], column.key) }}</template>
      </el-table-column>
    </el-table>
    <div v-if="result.rows.length > 50 && (showTable || ['table', 'card'].includes(chart))" class="result-pages"><span>共 {{ result.rows.length }} 个分组 · 每页 50 个 · 翻页无需重新查询</span><el-pagination v-model:current-page="page" :page-size="50" :total="result.rows.length" layout="prev, pager, next" aria-label="查询结果分页" /></div>
    <el-empty v-if="!result.rows.length" description="当前授权范围和筛选条件下暂无数据。" />
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { money } from './reportPresentation';
import { chartData, matrixRows } from './biLayout';
import { displayReportValue } from './reportDisplay';
const props = defineProps({
  result: { type: Object, required: true }, config: { type: Object, required: true }, dataset: { type: Object, required: true },
  type: { type: String, default: '' }, interaction: { type: String, default: 'drill' }, showTable: { type: Boolean, default: true }, maxHeight: { type: Number, default: 620 }, canInvestigate: { type: Boolean, default: false }
});
const emit = defineEmits(['drill', 'select', 'investigate']);
const chart = computed(() => props.type || props.config.chart);
const metric = computed(() => props.config.chart_metric || props.config.metrics[0]);
const label = key => [...props.dataset.dimensions, ...props.dataset.metrics].find(item => item.key === key)?.label || key;
const dimensionValue = (value, key) => props.result.dimension_labels?.[key]?.[String(value)] || displayReportValue(value, key);
const format = (value, key) => props.dataset.metrics.find(item => item.key === key)?.kind === 'money' ? money(value) : dimensionValue(value, key);
const page = ref(1), matrixRowPage = ref(1), matrixColumnPage = ref(1);
const pageRows = computed(() => props.result.rows.slice((page.value - 1) * 50, page.value * 50));
const matrix = computed(() => {
  const model = matrixRows(props.result.rows, props.config, metric.value);
  const columnKeys = props.config.field_layout?.columns?.length ? props.config.field_layout.columns : props.config.pivot ? [props.config.pivot] : [];
  const rowKeys = props.config.dimensions.filter(key => !columnKeys.includes(key));
  for (const row of model.rows) row.label = JSON.parse(row.id).map((value, index) => dimensionValue(value, rowKeys[index])).join(' · ') || '全部';
  for (const column of model.columns) column.label = JSON.parse(column.key).map((value, index) => dimensionValue(value, columnKeys[index])).join(' · ');
  return model;
});
const matrixPageRows = computed(() => matrix.value.rows.slice((matrixRowPage.value - 1) * 25, matrixRowPage.value * 25));
const matrixColumns = computed(() => matrix.value.columns.slice((matrixColumnPage.value - 1) * 12, matrixColumnPage.value * 12));
const chartModel = computed(() => {
  const model = chartData(props.result.rows, props.config, metric.value);
  for (const point of model.points) point.label = props.config.dimensions.map(key => dimensionValue(point.row[key], key)).join(' · ');
  return model;
});
watch(() => props.result, () => { page.value = 1; matrixRowPage.value = 1; matrixColumnPage.value = 1; });
const select = row => emit(props.interaction === 'select' ? 'select' : 'drill', row);
</script>
<style scoped>
.report-result { min-width: 0; display: grid; gap: 10px; }.result-note { color: #627086; font-size: 12px; line-height: 1.6; margin: 0; }
.report-chart { width: 100%; max-height: 340px; background: white; }.chart-point { cursor: pointer; }.chart-point:focus { outline: none; stroke: #172033; }
.report-chart text { font-size: 18px; fill: #526177; }.report-chart .point-value { fill: #172033; paint-order: stroke; stroke: white; stroke-width: 3px; }
.chart-legend { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 6px; }.chart-legend button { display: grid; gap: 4px; text-align: left; padding: 8px; border: 1px solid #e4e8f0; border-radius: 4px; background: #f8fafc; color: #526177; font-size: 12px; cursor: pointer; min-width: 0; overflow-wrap: anywhere; }.chart-legend strong { color: #172033; }
.matrix-scroll { min-width: 0; overflow: auto; }.pivot-table { border-collapse: collapse; font-size: 12px; }.pivot-table th, .pivot-table td { border: 1px solid #dce3ec; padding: 8px; white-space: nowrap; }.pivot-table th { background: #f1f5f9; }
.pivot-table button { border: 0; background: transparent; color: #5941c6; cursor: pointer; padding: 4px; }
.metric-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }.metric-cards button { background: #f8f6ff; border: 1px solid #e4dffc; border-radius: 6px; text-align: left; display: grid; gap: 8px; padding: 14px; cursor: pointer; min-width: 0; }
.metric-cards strong { font-size: 26px; color: #372f66; }.metric-cards span, .metric-cards small { color: #627086; font-size: 12px; overflow-wrap: anywhere; }
.report-result :deep(.el-table__row) { cursor: pointer; }
</style>
