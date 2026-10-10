<template>
  <section class="ads-report">
    <h1>{{ performance ? '广告投放分析' : '广告总览' }}</h1>
    <p>Shopee 已落库只读数据。查询不会调用平台、刷新令牌或执行同步。</p>
    <el-alert type="info" :closable="false" title="7 天点击归因：直接与广泛归因分别展示，不可相加。不同币种不合并；店铺与活动报表、日报与小时报表不重复汇总。广告消耗不是账单扣费。" />
    <el-alert v-if="kind.startsWith('gms_')" type="info" :closable="false" title="GMS 是整个采集区间的汇总，不是日报；日期筛选须与原采集区间一致，重叠区间和活动/商品报表不可重复相加。" />
    <el-form inline class="ads-filters" @submit.prevent="search">
      <el-form-item label="数据类型">
        <el-select v-model="kind" @change="search">
          <el-option v-for="option in kinds" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="店铺">
        <el-select v-model="storeId" clearable placeholder="全部可见店铺" @change="search">
          <el-option v-for="store in stores" :key="store.store_id" :value="store.store_id" :label="store.store__name" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="isDated" label="报表日期（店铺站点）">
        <el-date-picker v-model="period" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
      </el-form-item>
      <el-form-item><el-button type="primary" :loading="loading" @click="search">查询</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <el-skeleton v-if="loading" :rows="5" animated />
    <template v-else-if="!error">
      <el-empty v-if="!rows.length" description="暂无符合条件的广告数据。请先完成 Shopee 广告授权，在能力矩阵开启 ADVERTISING 只读能力，再创建并执行广告数据同步任务。" />
      <el-table v-else :data="rows" stripe border>
        <el-table-column prop="store_name" label="店铺" min-width="170" fixed />
        <el-table-column v-if="isDaily" prop="report_date" label="报表日期" width="120" />
        <el-table-column v-if="kind.startsWith('campaign') || kind.startsWith('gms_')" prop="campaign_id" label="活动 ID" min-width="150" />
        <el-table-column v-for="column in columns" :key="column.key" :label="column.label" min-width="135">
          <template #default="{ row }">{{ display(row.data[column.key]) }}</template>
        </el-table-column>
        <el-table-column v-if="isDated" label="CPC（消耗÷点击）" min-width="150">
          <template #default="{ row }">{{ ratio(row.data.expense, row.data.clicks) }}</template>
        </el-table-column>
        <el-table-column v-if="['balance', 'shop_toggle'].includes(kind)" label="平台快照时间" min-width="190">
          <template #default="{ row }">{{ snapshotTime(row.data.data_timestamp) }}</template>
        </el-table-column>
        <el-table-column prop="currency" label="币种" width="80" />
        <el-table-column prop="report_timezone" label="站点时区" min-width="180" />
        <el-table-column prop="source_run_id" label="来源运行编号" min-width="180" />
        <el-table-column label="更新时间" min-width="190">
          <template #default="{ row }">{{ snapshotTime(new Date(row.updated_at).getTime() / 1000) }}</template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="total" v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </template>
  </section>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchAdvertisingOverview, fetchAdvertisingPerformance } from '../api/advertising';
import { advertisingKinds } from '../utils/shopeeAdvertising';
const props = defineProps({ performance: Boolean });
const kind = ref(props.performance ? 'campaign_daily' : 'shop_daily');
const storeId = ref(null), period = ref(null), page = ref(1), total = ref(0);
const rows = ref([]), stores = ref([]), error = ref(''), loading = ref(false);
const kinds = advertisingKinds;
const isDaily = computed(() => kind.value.endsWith('_daily') || kind.value.endsWith('_hourly'));
const isDated = computed(() => isDaily.value || kind.value.startsWith('gms_'));
const columns = computed(() => {
  const entries = kind.value === 'campaign'
    ? [['ad_name', '活动名称'], ['campaign_status', '平台状态'], ['ad_type', '广告类型'], ['bidding_method', '出价方式'], ['campaign_placement', '投放位置'], ['campaign_budget', '预算（0=不限）'], ['item_id_list', '商品 ID'], ['roas_target', '目标 ROAS']]
    : kind.value === 'balance' ? [['total_balance', '广告总余额']]
    : kind.value === 'shop_toggle' ? [['auto_top_up', '自动充值开关'], ['campaign_surge', '活动加速开关']]
    : kind.value === 'recommended_item' ? [['item_id', '商品 ID'], ['item_status_list', '商品状态'], ['sku_tag_list', '推荐标签'], ['ongoing_ad_type_list', '当前投放类型']]
    : [['impression', '曝光'], ['clicks', '点击'], ['expense', '报表消耗'], ['direct_order', '直接归因订单'], ['broad_order', '广泛归因订单'], ['direct_gmv', '直接归因 GMV'], ['broad_gmv', '广泛归因 GMV'], [kind.value.startsWith('shop_') ? 'direct_roas' : 'direct_roi', '直接 ROAS'], [kind.value.startsWith('shop_') ? 'broad_roas' : 'broad_roi', '广泛 ROAS']];
  if (kind.value.endsWith('_hourly')) entries.unshift(['hour', '小时（站点时间）']);
  if (kind.value.startsWith('gms_')) entries.unshift(['period_start', '区间开始'], ['period_end', '区间结束']);
  if (kind.value === 'gms_item') entries.unshift(['item_id', '商品 ID']);
  return entries.map(([key, label]) => ({ key, label }));
});
const display = value => value == null ? '—' : typeof value === 'boolean' ? (value ? '开启' : '关闭') : Array.isArray(value) ? value.join(', ') : String(value);
const ratio = (a, b) => a == null || b == null || Number(b) === 0 ? '—' : (Number(a) / Number(b)).toFixed(4);
const snapshotTime = stamp => stamp ? new Date(stamp * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) + ' 北京时间' : '—';
let requestVersion = 0;
async function load() {
  const version = ++requestVersion;
  loading.value = true; error.value = ''; rows.value = [];
  try {
    const fetch = props.performance ? fetchAdvertisingPerformance : fetchAdvertisingOverview;
    const response = await fetch({ kind: kind.value, ...(storeId.value ? { store_id: storeId.value } : {}),
      ...(isDated.value && period.value ? { period_start: period.value[0], period_end: period.value[1] } : {}),
      page: page.value, page_size: 20 });
    if (version !== requestVersion) return;
    if (!response.success) throw new Error(response.message || '广告数据查询失败');
    rows.value = response.data.results; total.value = response.data.count; stores.value = response.data.stores;
  } catch (cause) {
    if (version === requestVersion) error.value = cause.message || '广告数据查询失败，请重试';
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}
function search() { page.value = 1; load(); }
onMounted(load);
</script>
<style scoped>
.ads-report { padding: 20px; }
.ads-report h1 { margin-top: 0; }
.ads-report p { color: var(--el-text-color-secondary); }
.ads-filters { margin-top: 20px; }
.ads-filters .el-select { width: 220px; }
.el-pagination { margin-top: 16px; }
@media (max-width: 700px) {
  .ads-report { padding: 12px; }
  .ads-filters :deep(.el-form-item) { display: flex; margin-right: 0; }
  .ads-filters :deep(.el-date-editor) { width: 100%; }
}
</style>
