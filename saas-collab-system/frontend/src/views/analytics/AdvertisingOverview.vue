<template>
  <el-tabs v-model="tab" class="advertising-overview-tabs">
    <el-tab-pane lazy label="广告总览" name="overview"><ShopeeAdvertisingReport /></el-tab-pane>
    <el-tab-pane lazy label="广告明细" name="details"><ShopeeAdvertisingReport :performance="true" /></el-tab-pane>
    <el-tab-pane v-if="canViewPeriods" lazy label="周期分析" name="periods"><PeriodAnalysis dataset="advertising" /></el-tab-pane>
    <el-tab-pane v-if="canViewPeriods" lazy label="国家／平台对比" name="comparison"><AnnualComparison dataset="advertising" /></el-tab-pane>
    <el-tab-pane lazy label="TikTok 已存竞价消耗" name="facts"><TikTokAdsDailySpendOverview :active="tab === 'facts'" /></el-tab-pane>
  </el-tabs>
</template>

<script setup>
import TikTokAdsDailySpendOverview from '../../components/TikTokAdsDailySpendOverview.vue';
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import ShopeeAdvertisingReport from '../../components/ShopeeAdvertisingReport.vue';
import PeriodAnalysis from '../../components/PeriodAnalysis.vue';
import AnnualComparison from '../../components/AnnualComparison.vue';

const auth = useAuthStore();
const tab = ref('overview');
const route = useRoute();
const canViewPeriods = computed(() => canAccessPath(auth.currentUser, '/reports/basic'));
watch(() => route.query.view, value => {
  if (value === 'details') tab.value = 'details';
  else if (value === 'overview') tab.value = 'overview';
}, { immediate: true });
</script>

<style scoped>
.advertising-overview-tabs { padding: 0 4px; }
</style>
