<template>
  <SalesOperations v-if="!legacy" @legacy="legacy = true" />
  <section v-else>
    <el-button class="return-operations" @click="legacy = false">← 返回日常经营</el-button>
    <el-tabs v-model="tab" class="sales-overview-tabs">
      <el-tab-pane label="明细查询" name="overview"><SalesWorkspace v-if="tab === 'overview'" mode="overview" /></el-tab-pane>
      <el-tab-pane v-if="canViewPeriods" lazy label="周期分析" name="periods"><PeriodAnalysis v-if="tab === 'periods'" dataset="sales" /></el-tab-pane>
      <el-tab-pane v-if="canViewPeriods" lazy label="国家／平台对比" name="comparison"><AnnualComparison v-if="tab === 'comparison'" /></el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import SalesOperations from './SalesOperations.vue';
const SalesWorkspace = defineAsyncComponent(() => import('./SalesWorkspace.vue'));
const PeriodAnalysis = defineAsyncComponent(() => import('../../components/PeriodAnalysis.vue'));
const AnnualComparison = defineAsyncComponent(() => import('../../components/AnnualComparison.vue'));

const auth = useAuthStore();
const route = useRoute();
// Historical report links with applied filters retain their original destination.
const legacy = ref(route.query.view !== 'operations' && Object.keys(route.query || {}).length > 0);
watch(() => route.query, query => { legacy.value = query.view !== 'operations' && Object.keys(query).length > 0; });
const tab = ref('overview');
const canViewPeriods = computed(() => canAccessPath(auth.currentUser, '/reports/basic'));
</script>

<style scoped>
.sales-overview-tabs { padding: 0 4px; }
.return-operations { margin: 8px 4px 16px; }
</style>
