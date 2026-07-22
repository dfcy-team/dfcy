<template><Phase2DataPage title="平台账单" note="GET /api/finance/statements/" :loader="fetchPlatformStatements" :columns="columns" :filter-configs="filters" empty-text="暂无平台账单" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchPlatformStatements } from '../../api/financeReconciliation';
const columns = [
  { prop: 'platform', label: '平台' }, { prop: 'statement_no', label: '账单号' }, { prop: 'period_start', label: '开始' },
  { prop: 'period_end', label: '结束' }, { prop: 'currency', label: '币种' }, { prop: 'gross_amount', label: '总额' },
  { prop: 'fee_amount', label: '费用' }, { prop: 'net_amount', label: '净额' }, { prop: 'status', label: '状态', type: 'status' }
];
const filters = [
  { key: 'platform', label: '平台', placeholder: 'demo-platform' },
  { key: 'currency', label: '币种', placeholder: 'USD' },
  { key: 'status', label: '状态', options: [{ label: '已导入', value: 'imported' }, { label: '匹配中', value: 'matching' }, { label: '已匹配', value: 'matched' }, { label: '异常', value: 'exception' }] }
];
</script>
