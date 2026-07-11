<template><Phase2DataPage title="平台账单" note="GET /api/finance/statements/" :loader="fetchPlatformStatements" :columns="columns" :filters="['平台','币种','状态']" empty-text="暂无平台账单" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchPlatformStatements } from '../../api/financeReconciliation';
const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'statement_no', label: '账单号' }, { prop: 'period_start', label: '开始' },
  { prop: 'period_end', label: '结束' }, { prop: 'currency', label: '币种' }, { prop: 'gross_amount', label: '总额' },
  { prop: 'fee_amount', label: '费用' }, { prop: 'net_amount', label: '净额' }, { prop: 'status', label: '状态', type: 'status' }
];
</script>
