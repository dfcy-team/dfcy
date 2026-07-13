<template>
  <Phase3DecisionPage
    eyebrow="库存决策"
    title="补货建议"
    subtitle="复核建议数量、日期、置信度与计算原因。"
    boundary-note="确认按钮仅为人工流程占位，不会生成采购订单、通知供应商或触发 RPA。"
    :loader="fetchReplenishmentRecommendations"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="待复核建议"
    table-note="低置信度建议应先补充数据证据"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { acceptReplenishmentRecommendation, fetchReplenishmentRecommendations, rejectReplenishmentRecommendation } from '../../api/replenishment';

const filters = [
  { key: 'status', label: '状态', options: [{ label: '待复核', value: 'pending' }, { label: '已确认', value: 'confirmed' }] },
  { key: 'confidence', label: '置信度', options: [{ label: '高', value: 'high' }, { label: '中', value: 'medium' }, { label: '低', value: 'low' }] }
];
const columns = [
  { prop: 'id', label: '建议编号', width: 150 }, { prop: 'sku', label: 'SKU', width: 140 },
  { prop: 'suggested_quantity', label: '建议数量' }, { prop: 'suggested_date', label: '建议日期', width: 130 },
  { prop: 'confidence', label: '置信度', type: 'confidence', width: 150 }, { prop: 'reason', label: '原因', width: 220 }, { prop: 'status', label: '状态', type: 'status' }
];
const rowActions = [
  { label: '查看证据', mode: 'detail' },
  { label: '人工接受建议', confirmMessage: '仅记录人工审核结果，不会创建采购订单、通知供应商或触发 RPA。', execute: (row) => acceptReplenishmentRecommendation(row.id, { reason: 'Human review accepted recommendation.' }) },
  { label: '人工拒绝建议', type: 'danger', confirmMessage: '仅记录人工审核结果，不会触发任何采购或自动化动作。', execute: (row) => rejectReplenishmentRecommendation(row.id, { reason: 'Human review rejected recommendation.' }) }
];
const detailFields = [
  { prop: 'id', label: '建议编号' }, { prop: 'reason_detail', label: '建议原因' }, { prop: 'confidence', label: '置信度' }, { prop: 'source_summary', label: '计算证据', type: 'json' }
];
</script>
