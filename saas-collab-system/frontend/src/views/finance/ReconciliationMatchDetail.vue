<template><Phase2DataPage title="对账匹配详情" note="GET /api/finance/reconciliation/matches/{id}/" mode="detail" :loader="() => fetchReconciliationMatchDetail(route.params.id || 1)" :detail-fields="fields" :actions="['确认占位','拒绝占位']" empty-text="暂无匹配详情" /></template>
<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchReconciliationMatchDetail } from '../../api/financeReconciliation';
const route = useRoute();
const fields = [
  { prop: 'match_type', label: '匹配类型' }, { prop: 'matched_amount', label: '匹配金额' }, { prop: 'difference_amount', label: '差异金额' },
  { prop: 'confidence', label: '置信度' }, { prop: 'status', label: '状态', type: 'status' }, { prop: 'reviewed_by', label: '复核人' },
  { prop: 'reviewed_at', label: '复核时间' }, { prop: 'audit_note', label: '审计提示' }
];
</script>
