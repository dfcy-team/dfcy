<template>
  <div class="recent-chart">
    <div v-if="!rows.length" class="empty">暂无已拉取数据</div>
    <template v-else>
      <div class="legend"><span>销售额（折线 · 右轴 {{ currency }}）</span><span class="orders">订单总量（柱形 · 左轴）</span><span class="shipped">已同步发货订单（柱形 · 左轴）</span></div>
      <svg @pointermove="moveTooltip" @pointerleave="hovered = null" viewBox="0 0 800 240" role="img" aria-label="近7日销售额折线、订单总量与已发货订单柱形图">
        <g v-for="tick in [0,1,2,3]" :key="tick">
          <path :d="`M55 ${195-tick*55} H735`" stroke="#33445b" stroke-dasharray="4 5" />
          <text x="48" :y="199-tick*55" text-anchor="end">{{ compact(orderMax*tick/3) }}</text>
          <text x="745" :y="199-tick*55">{{ compact(salesMax*tick/3) }}</text>
        </g>
        <g v-for="(row,index) in rows" :key="row.date">
          <rect v-if="known(row.order_count)" :x="x(index)-(known(row.shipped_order_count)?13:14)" :y="195-Number(row.order_count)/orderMax*165" :width="known(row.shipped_order_count)?12:28" :height="Number(row.order_count)/orderMax*165" fill="#edc650"><title>{{ row.date }} 订单总量：{{ row.order_count }}</title></rect>
          <rect v-if="known(row.shipped_order_count)" :x="x(index)+1" :y="195-Number(row.shipped_order_count)/orderMax*165" width="12" :height="Number(row.shipped_order_count)/orderMax*165" fill="#36b8e8"><title>{{ row.date }} 已发货订单：{{ row.shipped_order_count }}</title></rect>
          <circle v-if="known(row.sales_amount)" :cx="x(index)" :cy="195-Number(row.sales_amount)/salesMax*165" r="3" fill="#f4f8ff"><title>{{ row.date }} 销售额：{{ money(row.sales_amount) }} {{ currency }}</title></circle>
          <text :x="x(index)" y="222" text-anchor="middle">{{ String(row.date).slice(5) }}</text>
        </g>
        <path :d="salesPath" fill="none" stroke="#f4f8ff" stroke-width="2" />
        <rect v-for="(row,index) in rows" :key="'hit'+row.date" :x="x(index)-Math.min(40,310/Math.max(1,rows.length-1))" y="30" :width="Math.min(80,620/Math.max(1,rows.length-1))" height="165" fill="transparent" tabindex="0" :aria-label="rowLabel(row)" @pointerenter="showTooltip(index, $event)" @focus="showTooltip(index, $event)" @blur="hovered = null" />

      <g v-if="hovered != null" class="chart-crosshair" pointer-events="none" aria-hidden="true">
        <path :d="`M${x(hovered)} 30 V195 M55 ${focusY} H735`" stroke="#65e2d1" stroke-width="1" stroke-dasharray="4 3" />
        <rect x="0" :y="focusY-10" width="76" height="20" rx="3" fill="#24495a" />
        <text x="4" :y="focusY+4" fill="white">{{ compact(orderMax * (195-focusY)/165) }}</text>
        <rect x="724" :y="focusY-10" width="76" height="20" rx="3" fill="#24495a" />
        <text x="796" :y="focusY+4" text-anchor="end" fill="white">{{ compact(salesMax * (195-focusY)/165) }}</text>
        <rect :x="x(hovered)-29" y="207" width="58" height="21" rx="3" fill="#24495a" />
        <text :x="x(hovered)" y="222" text-anchor="middle" fill="white">{{ String(rows[hovered]?.date || '').slice(5) }}</text>
      </g>
    </svg>
      <div v-if="hovered != null && rows[hovered]" class="chart-tooltip" :style="tooltipPosition" role="tooltip">{{ rowLabel(rows[hovered]) }}</div>
      <details><summary>查看每日数值</summary><table><thead><tr><th>日期</th><th>订单量</th><th>已同步发货订单</th><th>销售额 {{ currency }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.date"><td>{{ row.date }}</td><td>{{ row.order_count ?? '—' }}</td><td>{{ known(row.shipped_order_count) ? row.shipped_order_count : '暂无已拉取数据' }}</td><td>{{ money(row.sales_amount) }}</td></tr></tbody></table></details>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
const props = defineProps<{ rows: Record<string, any>[], currency: string }>();
const hovered = ref<number | null>(null);
const focusY = ref(120);
const tooltipPosition = ref({ left: '12px', top: '12px' });
function moveTooltip(event: PointerEvent) {
  const target = event.currentTarget as SVGElement | null;
  const svg = target?.tagName?.toLowerCase() === 'svg' ? target : target?.ownerSVGElement;
  const bounds = svg?.getBoundingClientRect();
  if (bounds && bounds.height > 0) focusY.value = Math.max(30, Math.min(195, (event.clientY - bounds.top) / bounds.height * 240));
  const width = Math.min(320, window.innerWidth - 24);
  const left = event.clientX + 16 + width <= window.innerWidth - 12
    ? event.clientX + 16 : event.clientX - width - 16;
  const top = event.clientY + 16 + 120 <= window.innerHeight - 12
    ? event.clientY + 16 : event.clientY - 136;
  tooltipPosition.value = {
    left: Math.max(12, left) + 'px',
    top: Math.max(12, top) + 'px',
  };
}
function showTooltip(index: number, event: PointerEvent | FocusEvent) {
  hovered.value = index;
  if ('clientX' in event) moveTooltip(event as PointerEvent);
  else {
    const bounds = (event.currentTarget as Element).getBoundingClientRect();
    moveTooltip({ clientX: bounds.left + bounds.width / 2, clientY: bounds.top } as PointerEvent);
  }
}

watch(() => [props.rows, props.currency], () => { hovered.value = null; });
const rowLabel = (row: Record<string, any>) => row.date + ' · 订单总量 ' + (row.order_count ?? '暂无已拉取数据') + ' · 已发货订单 ' + (known(row.shipped_order_count) ? row.shipped_order_count : '暂无已拉取数据') + ' · 销售额 ' + (row.sales_amount == null ? '暂无已拉取数据' : Number(row.sales_amount).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ' + props.currency);
const money = (value: any) => value == null ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const known = (v: any) => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
const orderMax = computed(() => Math.max(1,...props.rows.flatMap(r=>[r.order_count,r.shipped_order_count]).filter(known).map(Number)));
const salesMax = computed(() => Math.max(1,...props.rows.filter(r=>known(r.sales_amount)).map(r=>Number(r.sales_amount))));
const x = (i: number) => 85 + i*620/Math.max(1,props.rows.length-1);
const compact = (v: number) => new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(v);
const salesPath = computed(() => { let connected=false; return props.rows.map((r,i)=>{ if(!known(r.sales_amount)){connected=false;return '';} const command=connected?'L':'M';connected=true;return `${command}${x(i)} ${195-Number(r.sales_amount)/salesMax.value*165}`; }).join(' '); });
</script>
<style scoped>
.chart-tooltip{position:fixed;z-index:10000;pointer-events:none;box-sizing:border-box;width:320px;max-width:calc(100vw - 24px);box-shadow:0 6px 24px #0006;padding:8px 10px;background:#1b293d;border:1px solid #3a6072;border-radius:5px;color:#eaf0fa;font-size:12px;line-height:1.7;white-space:normal}

.recent-chart{min-width:0}.legend{display:flex;justify-content:center;flex-wrap:wrap;gap:12px;color:#f4f8ff;font-size:12px}.orders{color:#edc650}.shipped{color:#36b8e8}.shipped{color:#36b8e8}svg{display:block;width:100%;height:220px}text{fill:#a9bbcf;font-size:11px}details{color:#a9bbcf;font-size:12px}summary{cursor:pointer}table{width:100%;text-align:left;margin-top:10px}td,th{padding:5px}.empty{padding:48px;text-align:center;color:#a9bbcf}
</style>
