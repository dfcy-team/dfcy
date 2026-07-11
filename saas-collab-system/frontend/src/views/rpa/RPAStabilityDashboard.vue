<template><Phase2DataPage title="RPA稳定性看板" note="GET /api/internal/rpa/tasks/ pending" risk-note="不调用 /api/rpa/* Agent执行端点，不执行真实RPA。" :loader="fetchRpaStabilityDashboard" :columns="columns" empty-text="暂无稳定性统计" /></template>
<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchRpaStabilityDashboard } from '../../api/rpaStability';
const columns = [{ prop: 'status', label: '状态', type: 'status' }, { prop: 'count', label: '数量' }];
</script>
