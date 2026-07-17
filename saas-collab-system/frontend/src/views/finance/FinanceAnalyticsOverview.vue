<template>
  <Phase3AnalyticsPage
    eyebrow="财务分析"
    title="财务经营分析"
    subtitle="查看脱敏后的账单、到账、对账差异与利润占位。"
    boundary-note="本页仅提供授权后的只读聚合分析，不执行付款、转账、提现或自动确认对账。"
    :loader="fetchFinanceAnalyticsOverview"
    :filters="filters"
    :columns="columns"
    trend-title="月度对账完成度"
    trend-note="演示指数用于观察财务数据完整性"
    trend-unit="指数"
    table-title="月度财务摘要"
    table-note="金额与银行账号默认聚合或掩码展示"
  />
</template>

<script setup>
import Phase3AnalyticsPage from '../../components/Phase3AnalyticsPage.vue';
import { fetchFinanceAnalyticsOverview } from '../../api/financeAnalytics';

const filters = [
  { key: 'date_range', label: '日期', type: 'daterange' },
  { key: 'currency', label: '币种', options: [{ label: 'CNY', value: 'CNY' }, { label: 'USD', value: 'USD' }, { label: 'EUR', value: 'EUR' }] }
];
const columns = [
  { prop: 'period_start', label: '开始日期' },
  { prop: 'period_end', label: '结束日期' },
  { prop: 'platform', label: '平台' },
  { prop: 'currency', label: '币种' },
  { prop: 'statement_amount', label: '账单金额', width: 140 },
  { prop: 'receipt_amount', label: '到账金额', width: 140 },
  { prop: 'difference_amount', label: '差异金额', width: 140 },
  { prop: 'exception_count', label: '异常数' },
  { prop: 'account_mask', label: '账号掩码', width: 130 },
  { prop: 'quality_status', label: '质量', type: 'status' }
];
</script>
