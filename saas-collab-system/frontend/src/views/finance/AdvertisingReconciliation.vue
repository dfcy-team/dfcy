<template>
  <Phase3AnalyticsPage
    eyebrow="财务中心"
    title="广告费用对账"
    subtitle="核对广告报表消耗、平台账单扣费和财务记录之间的差异。"
    boundary-note="广告费用数据尚未接入；当前不确认任何账单、付款或差异结果，待数据源接通后再进行三方核对。"
    :loader="fetchAdvertisingReconciliation"
    :filters="filters"
    :columns="columns"
    trend-title="广告费用核对趋势"
    trend-note="接入广告账单后按结算周期聚合"
    trend-unit="金额"
    table-title="广告费用核对明细"
    table-note="核对口径：广告报表消耗、平台账单扣费、财务入账；金额按币种展示"
    empty-text="广告费用数据尚未接入，暂无可对账记录"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchAdvertisingReconciliation } from '../../api/advertising';

const filters = [
  { key: 'date_range', label: '结算周期', type: 'daterange' },
  { key: 'platform', label: '平台', options: [] },
  { key: 'currency', label: '币种', options: [] },
  { key: 'status', label: '核对状态', options: [] }
];

const columns = [
  { prop: 'platform', label: '平台' },
  { prop: 'account', label: '广告账户' },
  { prop: 'period_start', label: '周期开始' },
  { prop: 'period_end', label: '周期结束' },
  { prop: 'currency', label: '币种' },
  { prop: 'report_spend', label: '报表消耗' },
  { prop: 'statement_charge', label: '账单扣费' },
  { prop: 'booked_amount', label: '财务入账' },
  { prop: 'difference_amount', label: '差异金额' },
  { prop: 'reconciliation_status', label: '核对状态', type: 'status' }
];
</script>
