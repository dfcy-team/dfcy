<template>
  <AppPage eyebrow="CONTROLLED PILOT" title="容量观察" subtitle="查看固定采样或受控环境回传的容量证据。" boundary-note="容量数据只用于观察和准入判断，不自动扩容、不执行基础设施命令。" :capability="capability">
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <el-alert :title="`数据质量：${data.quality_status}`" type="info" :closable="false" />
      <el-table class="table" :data="data.metrics" border>
        <el-table-column prop="service_name" label="服务" />
        <el-table-column prop="metric_code" label="指标" />
        <el-table-column prop="value" label="当前值" />
        <el-table-column prop="unit" label="单位" />
        <el-table-column prop="threshold" label="阈值" />
        <el-table-column prop="status" label="证据状态" />
        <el-table-column prop="observed_at" label="采样时间" min-width="180" />
        <el-table-column prop="expires_at" label="证据过期" min-width="180" />
      </el-table>
    </template>
  </AppPage>
</template>
<script setup>
import { ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchCapacitySummary } from '../../api/pilot';
import { statusFromApiResponse } from '../../utils/uiState';
const state = ref('loading'); const capability = ref('pending'); const errorMessage = ref(''); const data = ref({ metrics: [] });
async function load() { state.value = 'loading'; const response = await fetchCapacitySummary({ environment_id: 'controlled-pilot', window_minutes: 15 }); if (!response.success) { state.value = statusFromApiResponse(response, navigator.onLine); errorMessage.value = response.message; return; } data.value = response.data; capability.value = response.data.api_status || 'sandbox'; state.value = 'ready'; }
load();
</script>
<style scoped>.table{margin-top:14px}</style>
