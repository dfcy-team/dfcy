<template>
  <AdvertisingReportPlaceholder
    module="经营分析"
    :plan="advertisingReportPlans.performance"
    drilldown="计划 → 广告组 → 广告/商品/SKU；关键词或搜索词仅在来源支持时开放。"
    :metric-definitions="advertisingMetricDefinitions"
  />
</template>

<script setup>
import AdvertisingReportPlaceholder from '../../components/AdvertisingReportPlaceholder.vue';
import { advertisingMetricDefinitions, advertisingReportPlans } from '../../constants/advertisingReportPlans';
</script>
