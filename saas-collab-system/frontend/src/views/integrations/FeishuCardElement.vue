<template>
  <p v-if="element.tag === 'markdown'" class="card-markdown">{{ element.content }}</p>
  <hr v-else-if="element.tag === 'hr'" />
  <div v-else-if="element.tag === 'chart'" class="chart-preview">
    <strong>{{ element.chart_spec.title.text || '柱状图' }}</strong>
    <div class="chart-bars">
      <div v-for="point in element.chart_spec.data.values" :key="point.country" class="chart-row">
        <span>{{ point.country }}</span>
        <span class="chart-bar-track"><i :class="barClass(point.value)" :style="{ width: `${chartBarWidth(point.value)}%` }" /></span>
        <b>{{ point.value }}</b>
      </div>
    </div>
    <details><summary>查看原生 chart_spec 数据</summary><pre>{{ JSON.stringify(element.chart_spec, null, 2) }}</pre></details>
  </div>
  <div v-else-if="element.tag === 'button'" class="card-button-preview">
    <span>{{ element.text }}</span>
    <a v-if="element.url" :href="element.url" target="_blank" rel="noopener noreferrer">打开已校验 HTTPS 链接</a>
    <small v-else>未提供有效 HTTPS 链接</small>
  </div>
</template>

<script setup>
const props = defineProps({ element: { type: Object, required: true } });
const values = () => props.element.chart_spec.data.values;
function chartBarWidth(value) {
  const maxAbs = Math.max(0, ...values().map(point => Math.abs(point.value)));
  return maxAbs ? Math.abs(value) / maxAbs * 50 : 0;
}
function barClass(value) {
  return { 'chart-bar--positive': value > 0, 'chart-bar--negative': value < 0 };
}
</script>

<style scoped>
.card-markdown { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.chart-preview { display: grid; gap: 12px; }
.chart-bars { display: grid; gap: 8px; }
.chart-row { display: grid; grid-template-columns: minmax(60px, 100px) 1fr minmax(30px, auto); gap: 10px; align-items: center; font-size: 13px; }
.chart-bar-track { position: relative; height: 14px; overflow: hidden; border-radius: 7px; background: #e2e8f0; }
.chart-bar-track::after { position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; background: #64748b; content: ''; }
.chart-bar-track i { position: absolute; top: 0; height: 100%; border-radius: 7px; }
.chart-bar--positive { left: 50%; background: #409eff; }
.chart-bar--negative { right: 50%; background: #e66b6b; }
.chart-preview pre { max-height: 240px; overflow: auto; white-space: pre-wrap; }
.card-button-preview { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.card-button-preview > span { font-weight: 600; }
.card-button-preview small { color: #64748b; font-size: 12px; }
</style>
