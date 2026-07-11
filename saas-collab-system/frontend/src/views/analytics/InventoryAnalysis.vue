<template>
  <Phase3AnalyticsPage
    eyebrow="经营分析"
    title="库存分析"
    subtitle="查看库存结构、覆盖天数和周转风险。"
    boundary-note="库存指标仅用于只读分析；风险列表不会自动补货或生成采购订单。"
    :loader="fetchInventoryAnalysis"
    :filters="filters"
    :columns="columns"
    trend-title="库存覆盖趋势"
    trend-note="演示库存覆盖指数，越低需越早核查"
    trend-unit="指数"
    table-title="库存钻取"
    table-note="按仓库与 SKU 核对覆盖天数"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchInventoryAnalysis } from '../../api/analytics';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  { key: 'warehouse', label: '仓库', options: [{ label: '演示华东仓', value: 'demo-east' }, { label: '演示华南仓', value: 'demo-south' }] },
  { key: 'risk_level', label: '风险', options: [{ label: '高', value: 'high' }, { label: '中', value: 'medium' }, { label: '低', value: 'low' }] }
];

const columns = [
  { prop: 'sku_code', label: 'SKU', width: 140 }, { prop: 'product_name', label: '商品', width: 180 },
  { prop: 'warehouse', label: '仓库', width: 140 }, { prop: 'available_stock', label: '可售库存' },
  { prop: 'in_transit_stock', label: '在途库存' }, { prop: 'cover_days', label: '覆盖天数' },
  { prop: 'risk_level', label: '风险', type: 'status' }
];
</script>
