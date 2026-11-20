<template>
  <section v-if="rows.length" class="platform-advertising">
    <div class="platform-tabs" role="group" aria-label="广告平台">
      <button v-for="option in options" :key="option.value" type="button"
        :aria-pressed="selected === option.value" @click="selected = option.value">{{ option.label }}</button>
    </div>
    <article v-for="row in visibleRows" :key="row.platform" class="platform-advertising-row">
      <h3>{{ row.label }}</h3>
      <p v-if="row.platform === 'tiktok'" class="collection-delay" role="note">T+1 采集：次日采集前一日数据；“未入库”不代表零花费。</p>
      <dl>
        <div><dt>广告花费</dt><dd>{{ amount(row.ad_spend) }} {{ row.ad_spend == null ? '' : currency }}</dd></div>
        <div><dt>整店 ROI</dt><dd>{{ row.store_roi == null ? (Number(row.ad_spend) === 0 && row.ad_spend != null ? '花费为零，无法计算' : '暂无可计算数据') : amount(row.store_roi) + ' 倍' }}</dd></div>
        <div><dt>销售金额</dt><dd>{{ amount(row.sales_amount) }} {{ currency }}</dd></div>
        <div v-if="row.platform === 'shopee'"><dt>广告点击量</dt><dd>{{ row.clicks == null ? '暂无已入库数据' : Number(row.clicks).toLocaleString('zh-CN') }}</dd></div>
      </dl>
      <p v-if="row.partial" role="status">有在途数据，后续同步后更新。</p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';

type PlatformAdvertising = {
  platform: string;
  label: string;
  ad_spend: string | number | null;
  sales_amount: string | number;
  store_roi: string | number | null;
  clicks: number | null;
  partial: boolean;
};
const props = defineProps<{ rows: PlatformAdvertising[]; currency: string }>();
const selected = ref('all');
const options = computed(() => [
  { value: 'all', label: '全部' },
  ...props.rows.map(row => ({ value: row.platform, label: row.label })),
]);
const visibleRows = computed(() => selected.value === 'all' ? props.rows : props.rows.filter(row => row.platform === selected.value));
const amount = (value: string | number | null) => value == null || !Number.isFinite(Number(value))
  ? '暂无已入库数据'
  : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
</script>

<style scoped>
.platform-tabs{display:flex;gap:6px;margin:12px 0}
.platform-tabs button{border:1px solid #344359;border-radius:5px;padding:6px 10px;background:transparent;color:#eaf0fa;cursor:pointer}
.platform-tabs button[aria-pressed="true"]{background:#23463f;border-color:#55d6be;color:#66dfc8}
.platform-advertising-row{border-top:1px solid #26354b;padding:12px 0}
h3{font-size:13px;margin:0 0 10px}
dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0}
dt,p{font-size:11px;color:#94a6bf}
dd{font-size:14px;margin:6px 0 0;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
p{margin:10px 0 0}
</style>
