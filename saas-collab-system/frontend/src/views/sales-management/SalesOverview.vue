<template>
  <el-tabs v-model="tab" class="sales-overview-tabs">
    <el-tab-pane label="销售总览" name="overview"><SalesWorkspace mode="overview" /></el-tab-pane>
    <el-tab-pane v-if="canViewPeriods" label="周期分析" name="periods"><PeriodAnalysis dataset="sales" /></el-tab-pane>
    <el-tab-pane v-if="canViewPeriods" lazy label="国家／平台对比" name="comparison"><AnnualComparison /></el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { computed, ref } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import SalesWorkspace from './SalesWorkspace.vue';
import PeriodAnalysis from '../../components/PeriodAnalysis.vue';
import AnnualComparison from '../../components/AnnualComparison.vue';

const auth = useAuthStore();
const tab = ref('overview');
const canViewPeriods = computed(() => canAccessPath(auth.currentUser, '/reports/basic'));
</script>

<style scoped>
.sales-overview-tabs { padding: 0 4px; }
</style>
