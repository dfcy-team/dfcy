<template>
  <div class="hourly-chart">
    <div class="legend"><span class="yesterday">■ 昨日每小时</span><span class="today">■ 今日每小时</span><span>━ 今日累计（右轴）</span></div>
    <svg viewBox="0 0 800 250" role="img" :aria-label="metric === 'sales_amount' ? '今日昨日小时销售额与今日累计' : '今日昨日小时订单量与今日累计'">
      <text x="20" y="15">{{ format(maximum) }} {{ unit }}</text><text x="780" y="15" text-anchor="end">{{ format(total) }} {{ unit }}</text>
      <path d="M20 30H780 M20 120H780 M20 210H780" stroke="#344359" stroke-dasharray="4 6"/>
      <rect v-for="row in previous" :key="'p'+row.date" :x="x(row.date)-10" :y="y(row[metric])" width="9" :height="210-y(row[metric])" fill="#edc650"><title>昨日 {{ row.date }}：{{ format(row[metric]) }} {{ unit }}</title></rect>
      <rect v-for="row in current" :key="'c'+row.date" :x="x(row.date)+1" :y="y(row[metric])" width="9" :height="210-y(row[metric])" fill="#40c5e9"><title>今日 {{ row.date }}：{{ format(row[metric]) }} {{ unit }}</title></rect>
      <polyline :points="line" stroke="#fff" stroke-width="2" fill="none"/>
      <circle v-for="point in cumulative" :key="point.date" :cx="x(point.date)" :cy="210-point.value/total*180" r="3" fill="white"><title>{{ point.date }} 今日累计：{{ format(point.value) }} {{ unit }}</title></circle>
      <text v-for="hour in [0,4,8,12,16,20,23]" :key="hour" :x="x(String(hour))" y="235" text-anchor="middle">{{ String(hour).padStart(2,'0') }}:00</text>
    </svg>
    <p>柱形为当小时已拉取数据；白线为今日已拉取累计。空缺时段不代表零成交，未来时段不绘制。</p>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue';
type Row = Record<string, any>;
const props = defineProps<{ current: Row[], previous: Row[], metric: string, unit: string }>();
const maximum = computed(() => Math.max(1,...[...props.current,...props.previous].map(r=>Number(r[props.metric])||0)));
const cumulative = computed(() => { let sum=0; return [...props.current].sort((a,b)=>a.date.localeCompare(b.date)).map(r=>({date:r.date,value:sum+=Number(r[props.metric])||0})); });
const total = computed(()=>Math.max(1,cumulative.value.at(-1)?.value||0));
const x=(date:string)=>30+Number(date.slice(0,2))*740/23;
const y=(value:any)=>210-Math.max(0,Number(value)||0)/maximum.value*180;
const format=(value:any)=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});
const line=computed(()=>cumulative.value.map(p=>`${x(p.date)},${210-p.value/total.value*180}`).join(' '));
</script>
<style scoped>
.hourly-chart svg{display:block;width:100%;min-height:220px}.hourly-chart text{fill:#a4b6cb;font-size:11px}.legend{display:flex;gap:18px;justify-content:center;font-size:12px;color:white}.yesterday{color:#edc650}.today{color:#40c5e9}p{font-size:11px;color:#9caec3}
</style>
