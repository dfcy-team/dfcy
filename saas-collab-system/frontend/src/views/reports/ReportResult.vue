<template>
  <div class="report-result">
    <template v-if="chart === 'card'">
      <p class="result-note">各分组分别显示，不跨币种或跨 SKU 合计。</p>
      <div class="metric-cards"><button v-for="(row, index) in result.rows" :key="index" type="button" @click="select(row)">
        <span>{{ config.dimensions.map(key => present(row[key])).join(' · ') }}</span>
        <strong>{{ format(row[metric], metric) }}</strong><small>{{ label(metric) }}</small>
      </button></div>
    </template>
    <template v-else-if="chart === 'pivot' && matrix.columns.length">
      <p class="result-note">缺失单元格不补零；点击单元格可{{ interaction === 'select' ? '联动其他组件' : '穿透明细' }}。</p>
      <div class="matrix-scroll"><table class="pivot-table"><thead><tr><th>分组</th><th v-for="column in matrix.columns" :key="column.key">{{ column.label }}</th></tr></thead>
        <tbody><tr v-for="row in matrix.rows" :key="row.id"><th>{{ row.label }}</th><td v-for="column in matrix.columns" :key="column.key">
          <button v-if="row.cells[column.key]" type="button" @click="select(row.cells[column.key].source)">{{ format(row.cells[column.key].value, metric) }}</button><span v-else>—</span>
        </td></tr></tbody></table></div>
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
    <el-table v-if="showTable || chart === 'table'" :data="result.rows" stripe :max-height="maxHeight" @row-click="select">
      <el-table-column v-for="column in result.columns" :key="column.key" :prop="column.key" :label="column.label" min-width="140">
        <template #default="{ row }">{{ format(row[column.key], column.key) }}</template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!result.rows.length" description="当前授权范围和筛选条件下暂无数据。" />
  </div>
</template>
<script setup>
import { computed } from 'vue';
import { money, present } from './reportPresentation';
import { chartData, matrixRows } from './biLayout';
const props = defineProps({
  result: { type: Object, required: true }, config: { type: Object, required: true }, dataset: { type: Object, required: true },
  type: { type: String, default: '' }, interaction: { type: String, default: 'drill' }, showTable: { type: Boolean, default: true }, maxHeight: { type: Number, default: 620 }
});
const emit = defineEmits(['drill', 'select']);
const chart = computed(() => props.type || props.config.chart);
const metric = computed(() => props.config.chart_metric || props.config.metrics[0]);
const label = key => [...props.dataset.dimensions, ...props.dataset.metrics].find(item => item.key === key)?.label || key;
const format = (value, key) => props.dataset.metrics.find(item => item.key === key)?.kind === 'money' ? money(value) : present(value);
const matrix = computed(() => matrixRows(props.result.rows, props.config, metric.value));
const chartModel = computed(() => chartData(props.result.rows, props.config, metric.value));
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
