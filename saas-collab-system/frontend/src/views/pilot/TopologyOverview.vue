<template>
  <AppPage eyebrow="CONTROLLED PILOT" title="部署拓扑" subtitle="只展示掩码后的主机角色、网络区和暴露范围。" boundary-note="固定校验不会探测主机、端口或网络，也不会执行远程命令。" :capability="capability">
    <template #action><el-button v-if="auth.hasPermission('pilot.topology.verify')" type="primary" :loading="checking" @click="verify">固定校验</el-button></template>
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <el-table v-else :data="data.services" border>
      <el-table-column prop="service_name" label="服务" />
      <el-table-column prop="host_role" label="主机角色" />
      <el-table-column prop="network_zone" label="网络区" />
      <el-table-column prop="exposure" label="暴露范围" />
      <el-table-column prop="masked_endpoint" label="掩码端点" min-width="180" />
      <el-table-column prop="health_status" label="健康状态" width="120" />
      <el-table-column prop="checked_at" label="校验时间" min-width="180" />
    </el-table>
  </AppPage>
</template>
<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchPilotTopology, verifyPilotTopologyMock } from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';
const auth = useAuthStore(); const state = ref('loading'); const capability = ref('pending'); const errorMessage = ref(''); const checking = ref(false); const data = ref({ services: [] });
async function load() { state.value = 'loading'; const response = await fetchPilotTopology({ environment_id: 'controlled-pilot' }); if (!response.success) { state.value = statusFromApiResponse(response, navigator.onLine); errorMessage.value = response.message; return; } data.value = response.data; capability.value = response.data.api_status || 'sandbox'; state.value = 'ready'; }
async function verify() { checking.value = true; const services = data.value.services.map(({ service_name, host_role, network_zone, exposure }) => ({ service_name, host_role, network_zone, exposure })); const response = await verifyPilotTopologyMock({ environment_id: data.value.environment_id, services, reason: 'fixed demo topology verification' }); ElMessage[response.success && response.data.valid ? 'success' : 'error'](response.success && response.data.valid ? '固定校验通过' : response.message || '校验未通过'); checking.value = false; }
load();
</script>
