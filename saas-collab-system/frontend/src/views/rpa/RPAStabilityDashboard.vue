<template>
  <section class="stability-page">
    <header class="stability-header">
      <div>
        <h1 class="page-title">RPA稳定性</h1>
        <p>GET /api/internal/rpa/stability/</p>
      </div>
      <el-tag :type="state === 'connected' ? 'success' : state === 'error' ? 'danger' : 'info'">{{ state }}</el-tag>
    </header>
    <el-alert title="任务状态与运行状态分开统计；本页不调用任何 Agent 执行动作。" type="warning" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" type="error" show-icon :closable="false" />
    <div class="metric-grid" v-loading="loading">
      <el-card shadow="never"><el-statistic title="待人工处理" :value="summary.manual_required || 0" /></el-card>
      <el-card shadow="never"><el-statistic title="任务状态种类" :value="taskStates.length" /></el-card>
      <el-card shadow="never"><el-statistic title="运行状态种类" :value="runStates.length" /></el-card>
    </div>
    <div class="state-grid">
      <el-card shadow="never">
        <template #header>任务状态机</template>
        <el-table :data="taskStates" border empty-text="暂无任务状态"><el-table-column prop="status" label="状态" /><el-table-column prop="count" label="数量" /></el-table>
      </el-card>
      <el-card shadow="never">
        <template #header>运行状态机</template>
        <el-table :data="runStates" border empty-text="暂无运行状态"><el-table-column prop="status" label="状态" /><el-table-column prop="count" label="数量" /></el-table>
      </el-card>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchRpaStabilityDashboard } from '../../api/rpaStability';

const summary = ref({});
const loading = ref(false);
const state = ref('loading');
const message = ref('');
const taskStates = computed(() => summary.value.task_states || summary.value.items || []);
const runStates = computed(() => summary.value.run_states || []);

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchRpaStabilityDashboard();
    if (!response.success) throw new Error(response.message || '稳定性接口失败');
    summary.value = response.data || {};
    state.value = response.data?.api_status || response.data?.status || 'mock';
  } catch (error) {
    state.value = 'error';
    message.value = error?.message || '稳定性接口失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.stability-page { display: grid; gap: 16px; }
.stability-header { display: flex; justify-content: space-between; gap: 16px; }
.stability-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.state-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 900px) { .metric-grid, .state-grid { grid-template-columns: 1fr; } }
</style>
