<template>
  <section>
    <ShopeeAdvertisingReport v-if="platform === 'shopee'" :key="`${platform}-${performance}`" :performance="performance" :fixed-platform="platform" />
    <TikTokAdsDailySpendOverview v-else :key="`${platform}-${performance}`" :performance="performance" :active="true" />
  </section>
</template>

<script setup>
import ShopeeAdvertisingReport from '../../components/ShopeeAdvertisingReport.vue';
import TikTokAdsDailySpendOverview from '../../components/TikTokAdsDailySpendOverview.vue';

defineProps({ platform: { type: String, required: true }, performance: Boolean });
</script>
