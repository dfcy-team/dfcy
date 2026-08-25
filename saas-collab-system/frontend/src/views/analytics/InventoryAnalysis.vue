<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="库存分析"
    subtitle="查看库存结构、覆盖天数和周转风险。"
    boundary-note="库存指标仅用于只读分析；风险列表不会自动补货或生成采购订单。"
    :loader="fetchInventoryAnalysis"
    :options-loader="fetchAnalyticsFilters"
    :filters="filters"
    :columns="columns"
    presentation="operating"
    metrics-key="summary_metrics"
    :metric-columns="3"
    :page-size="50"
    :table-max-height="720"
    trend-value-key="available_qty"
    trend-label-separator="/"
    trend-count-unit="个快照"
    quality-middle-label="数据来源"
    quality-middle-value="极风 WMS 手动快照"
    quality-middle-fallback="极风 WMS 手动快照"
    :show-metric-code="false"
    trend-title="库存快照趋势"
    trend-note="每次人工写入形成一个快照数据点，展示可用库存变化。"
    table-title="库存明细"
    table-note="每个站点、仓库、SKU 仅展示最新一次已写入快照。"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchAnalyticsFilters, fetchInventoryAnalysis } from '../../api/analytics';

const filters = [
  { key: 'site_code', label: '站点', optionSource: 'sites', placeholder: '全部站点', clears: ['warehouse_id'] },
  { key: 'warehouse_id', label: '仓库', optionSource: 'warehouses', placeholder: '全部仓库', dependsOn: 'site_code', optionField: 'site' },
  { key: 'risk', label: '库存风险', placeholder: '全部风险', options: [
    { label: '缺货', value: 'out' }, { label: '低库存', value: 'low' },
    { label: '锁定偏高', value: 'locked' }, { label: '正常', value: 'healthy' }
  ] }
];

const columns = [
  { prop: 'source_sku', secondaryProp: 'product_name', secondaryFallback: '未返回商品名称', label: '商品', type: 'primary', width: 260 },
  { prop: 'site_code', secondaryProp: 'warehouse_code', label: '站点 / 仓库', type: 'dual', width: 150 },
  { prop: 'on_hand_qty', label: '总库存', type: 'number' },
  { prop: 'available_qty', label: '可用', type: 'number' },
  { prop: 'reserved_qty', label: '锁定', type: 'number' },
  { prop: 'in_transit_qty', label: '在途', type: 'number' },
  { prop: 'pending_putaway_qty', label: '待上架', type: 'number' },
  { prop: 'defective_qty', label: '不良品', type: 'number' },
  { prop: 'risk_label', statusProp: 'risk', label: '风险', type: 'status' },
  { prop: 'snapshot_at_utc', label: '快照时间', type: 'datetime', width: 180 }
];
</script>
