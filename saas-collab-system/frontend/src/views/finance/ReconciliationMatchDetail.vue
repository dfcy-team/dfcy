<template>
  <Phase2DataPage
    title="对账匹配详情"
    note="后端阶段2仅提供 GET /api/finance/reconciliation/matches/ 集合查询；详情页使用集合数据展示。"
    risk-note="确认或拒绝对账结果必须走 /api/finance/* 后端授权接口。"
    mode="detail"
    :loader="() => fetchReconciliationMatchDetail(route.params.id || 1)"
    :detail-fields="fields"
    :action-configs="actionConfigs"
    empty-text="暂无匹配详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import {
  confirmReconciliationMatch,
  fetchReconciliationMatchDetail,
  rejectReconciliationMatch
} from '../../api/financeReconciliation';

const route = useRoute();

const fields = [
  { prop: 'match_type', label: '匹配类型' },
  { prop: 'matched_amount', label: '匹配金额' },
  { prop: 'difference_amount', label: '差异金额' },
  { prop: 'confidence', label: '置信度' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'reviewed_by_id', label: '复核人' },
  { prop: 'reviewed_at', label: '复核时间' },
  { prop: 'audit_note', label: '审计提示' }
];

const actionConfigs = [
  {
    label: '确认匹配',
    type: 'primary',
    confirmMessage: '确认对账匹配属于财务高风险操作，必须以后端财务权限为准。',
    handler: () => confirmReconciliationMatch(route.params.id || 1)
  },
  {
    label: '拒绝匹配',
    confirmMessage: '拒绝对账匹配将调用后端财务 reject 接口。',
    handler: () => rejectReconciliationMatch(route.params.id || 1)
  }
];
</script>
