<template>
  <Phase3DecisionPage
    eyebrow="库存决策"
    title="库存预警"
    subtitle="识别缺货、超储和数据质量风险。"
    boundary-note="预警仅用于分析，不会自动补货、通知真实供应商或触发 RPA。"
    :loader="fetchInventoryAlerts"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="库存风险"
    table-note="优先核查高风险和质量异常数据"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchInventoryAlerts } from '../../api/replenishment';

const filters = [
  { key: 'alert_type', label: '类型', options: [{ label: '缺货', value: 'stockout' }, { label: '超储', value: 'overstock' }] },
  { key: 'risk_level', label: '等级', options: [{ label: '高', value: 'high' }, { label: '中', value: 'medium' }, { label: '低', value: 'low' }] }
];
const columns = [
  { prop: 'alert_id', label: '预警编号', width: 150 }, { prop: 'sku_code', label: 'SKU', width: 140 }, { prop: 'warehouse', label: '仓库', width: 140 },
  { prop: 'alert_type', label: '类型' }, { prop: 'risk_level', label: '等级', type: 'status' }, { prop: 'cover_days', label: '覆盖天数' },
  { prop: 'reason', label: '原因', width: 220 }, { prop: 'quality_status', label: '质量', type: 'status' }
];
const rowActions = [{ label: '查看证据', mode: 'detail' }];
const detailFields = [
  { prop: 'alert_id', label: '预警编号' }, { prop: 'reason', label: '预警原因' }, { prop: 'evidence', label: '指标证据', type: 'json' }
];
</script>
