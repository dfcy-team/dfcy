<template>
  <AdvertisingReportPlaceholder
    module="财务中心"
    :plan="advertisingReportPlans.reconciliation"
    drilldown="账户与结算周期 → 账单条目 → 财务流水；处理差异时保留核对依据与审计记录。"
    :metric-definitions="advertisingReconciliationDefinitions"
    definition-note="按广告账户、结算周期和币种核对，先统一税费、退款与调整口径；报表消耗、账单扣费与财务入账的差额分别保留。"
  />
</template>

<script setup>
import AdvertisingReportPlaceholder from '../../components/AdvertisingReportPlaceholder.vue';
import { advertisingReconciliationDefinitions, advertisingReportPlans } from '../../constants/advertisingReportPlans';
</script>
