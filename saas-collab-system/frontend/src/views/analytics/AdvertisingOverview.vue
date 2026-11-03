<template>
  <el-tabs v-model="tab" class="advertising-overview-tabs">
    <el-tab-pane lazy label="周期分析" name="periods">
      <PeriodAnalysis v-if="canViewPeriods" dataset="advertising" />
      <el-empty v-else description="你没有查看基础报表的权限" />
    </el-tab-pane>
    <el-tab-pane lazy label="国家／平台对比" name="comparison">
      <AnnualComparison v-if="canViewPeriods" dataset="advertising" />
      <el-empty v-else description="你没有查看基础报表的权限" />
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { computed, ref } from 'vue';
import { useAuthStore } from '../../stores/auth';
import { canAccessPath } from '../../router/menu';
import PeriodAnalysis from '../../components/PeriodAnalysis.vue';
import AnnualComparison from '../../components/AnnualComparison.vue';

const auth = useAuthStore();
const tab = ref('periods');
const canViewPeriods = computed(() => canAccessPath(auth.currentUser, '/reports/basic'));
</script>

<style scoped>
.advertising-overview-tabs { padding: 0 4px; }
</style>
