<template>
  <div class="recent-chart">
    <div v-if="!rows.length" class="empty">暂无已拉取数据</div>
    <template v-else>
      <div class="legend"><span>销售额（折线 · 右轴 {{ currency }}）</span><span class="orders">订单总量（柱形 · 左轴）</span></div>
      <svg viewBox="0 0 800 240" role="img" aria-label="近7日销售额折线与订单总量柱形图">
        <g v-for="tick in [0,1,2,3]" :key="tick">
          <path :d="`M55 ${195-tick*55} H735`" stroke="#33445b" stroke-dasharray="4 5" />
          <text x="48" :y="199-tick*55" text-anchor="end">{{ compact(orderMax*tick/3) }}</text>
          <text x="745" :y="199-tick*55">{{ compact(salesMax*tick/3) }}</text>
        </g>
        <g v-for="(row,index) in rows" :key="row.date">
          <rect v-if="known(row.order_count)" :x="x(index)-14" :y="195-Number(row.order_count)/orderMax*165" width="28" :height="Number(row.order_count)/orderMax*165" fill="#edc650"><title>{{ row.date }} 订单总量：{{ row.order_count }}</title></rect>
          <circle v-if="known(row.sales_amount)" :cx="x(index)" :cy="195-Number(row.sales_amount)/salesMax*165" r="3" fill="#f4f8ff"><title>{{ row.date }} 销售额：{{ row.sales_amount }} {{ currency }}</title></circle>
          <text :x="x(index)" y="222" text-anchor="middle">{{ String(row.date).slice(5) }}</text>
        </g>
        <path :d="salesPath" fill="none" stroke="#f4f8ff" stroke-width="2" />
      </svg>
      <details><summary>查看每日数值</summary><table><thead><tr><th>日期</th><th>订单量</th><th>销售额 {{ currency }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.date"><td>{{ row.date }}</td><td>{{ row.order_count ?? '—' }}</td><td>{{ row.sales_amount ?? '—' }}</td></tr></tbody></table></details>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{ rows: Record<string, any>[], currency: string }>();
const known = (v: any) => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
const orderMax = computed(() => Math.max(1,...props.rows.filter(r=>known(r.order_count)).map(r=>Number(r.order_count))));
const salesMax = computed(() => Math.max(1,...props.rows.filter(r=>known(r.sales_amount)).map(r=>Number(r.sales_amount))));
const x = (i: number) => 85 + i*620/Math.max(1,props.rows.length-1);
const compact = (v: number) => new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(v);
const salesPath = computed(() => { let connected=false; return props.rows.map((r,i)=>{ if(!known(r.sales_amount)){connected=false;return '';} const command=connected?'L':'M';connected=true;return `${command}${x(i)} ${195-Number(r.sales_amount)/salesMax.value*165}`; }).join(' '); });
</script>
<style scoped>
.recent-chart{min-width:0}.legend{display:flex;justify-content:center;flex-wrap:wrap;gap:12px;color:#f4f8ff;font-size:12px}.orders{color:#edc650}svg{display:block;width:100%;height:220px}text{fill:#a9bbcf;font-size:11px}details{color:#a9bbcf;font-size:12px}summary{cursor:pointer}table{width:100%;text-align:left;margin-top:10px}td,th{padding:5px}.empty{padding:48px;text-align:center;color:#a9bbcf}
</style>
