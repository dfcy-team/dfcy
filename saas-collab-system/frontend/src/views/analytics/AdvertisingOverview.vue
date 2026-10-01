<template>
  <AdvertisingReportPlaceholder
    module="经营分析"
    :plan="advertisingReportPlans.overview"
    drilldown="平台 → 广告账户 → 店铺 → 计划 → 商品/SKU，携带日期、币种及归因口径。"
    :metric-definitions="advertisingMetricDefinitions"
  />
</template>

<script setup>
import AdvertisingReportPlaceholder from '../../components/AdvertisingReportPlaceholder.vue';
import { advertisingMetricDefinitions, advertisingReportPlans } from '../../constants/advertisingReportPlans';
</script>
