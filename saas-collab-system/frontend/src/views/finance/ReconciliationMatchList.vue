<template><Phase2DataPage title="对账匹配" note="GET /api/finance/reconciliation/matches/" risk-note="自动匹配只产生建议，最终确认需要后端财务授权。" :loader="fetchReconciliationMatches" :columns="columns" :actions="['人工确认占位','拒绝占位']" empty-text="暂无匹配记录" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchReconciliationMatches } from '../../api/financeReconciliation';
const columns = [
  { prop: 'match_type', label: '匹配类型' }, { prop: 'matched_amount', label: '匹配金额' }, { prop: 'difference_amount', label: '差异金额' },
  { prop: 'confidence', label: '置信度' }, { prop: 'status', label: '状态', type: 'status' }, { prop: 'reviewed_by', label: '复核人' }, { prop: 'reviewed_at', label: '复核时间' }
];
</script>
