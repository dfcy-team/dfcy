<template>
  <Phase2DataPage
    title="对账匹配"
    note="GET /api/finance/reconciliation/matches/"
    risk-note="自动匹配只产生建议，最终确认或拒绝必须走后端财务授权接口。"
    :loader="fetchReconciliationMatches"
    :columns="columns"
    :filter-configs="filters"
    :action-configs="actionConfigs"
    empty-text="暂无匹配记录"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchReconciliationMatches, runReconciliationMock } from '../../api/financeReconciliation';

const columns = [
  { prop: 'match_type', label: '匹配类型' },
  { prop: 'matched_amount', label: '匹配金额' },
  { prop: 'difference_amount', label: '差异金额' },
  { prop: 'confidence', label: '置信度' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'reviewed_by_id', label: '复核人' },
  { prop: 'reviewed_at', label: '复核时间' }
];

const filters = [
  { key: 'platform', label: '平台', placeholder: 'demo-platform' },
  { key: 'currency', label: '币种', placeholder: 'USD' },
  { key: 'status', label: '状态', options: [{ label: '待复核', value: 'suggested' }, { label: '已确认', value: 'confirmed' }, { label: '已拒绝', value: 'rejected' }] }
];

const actionConfigs = [
  {
    label: 'run-mock',
    permission: 'finance.reconcile',
    type: 'primary',
    confirmMessage: '仅运行后端 Mock 对账，不接入真实银行或支付平台。',
    handler: () => runReconciliationMock()
  }
];
</script>
