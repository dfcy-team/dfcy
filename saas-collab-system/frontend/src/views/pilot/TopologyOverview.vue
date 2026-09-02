<template>
  <AppPage eyebrow="PRODUCTION PILOT" title="部署拓扑" subtitle="查看受控部署的主机角色、网络区和暴露范围，并执行固定拓扑校验（mock）。" boundary-note="拓扑校验当前为 fixed-demo/mock 静态边界校验，只用于证据演示，不代表真实部署运行时状态。" :capability="capability">
    <template #action><el-button v-if="auth.hasPermission('pilot.topology.verify')" type="primary" :loading="checking" @click="verify">执行固定拓扑校验（mock）</el-button></template>
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
    <el-alert v-if="verificationError" class="verification-result" type="error" :closable="false" title="固定拓扑校验请求失败" :description="verificationError" />
    <el-alert v-if="verificationResult" class="verification-result" :type="verificationResult.valid ? 'success' : 'error'" :closable="false" :title="`固定拓扑校验（fixed-demo/mock）${verificationResult.valid ? '通过' : '未通过'}`" :description="JSON.stringify(verificationResult)" />
  </AppPage>
</template>
<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchPilotTopology, verifyPilotTopology } from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';
const auth = useAuthStore(); const state = ref('loading'); const capability = ref('connected'); const errorMessage = ref(''); const checking = ref(false); const data = ref({ services: [] }); const verificationResult = ref(null); const verificationError = ref('');
async function load() { state.value = 'loading'; const response = await fetchPilotTopology({ environment_id: 'controlled-pilot' }); if (!response.success) { state.value = statusFromApiResponse(response, typeof navigator === 'undefined' || navigator.onLine); errorMessage.value = response.message; return; } data.value = response.data; capability.value = response.data?.api_status || 'connected'; state.value = 'ready'; }
async function verify() { verificationError.value = ''; verificationResult.value = null; checking.value = true; const services = data.value.services.map(({ service_name, host_role, network_zone, exposure }) => ({ service_name, host_role, network_zone, exposure })); const response = await verifyPilotTopology({ environment_id: data.value.environment_id, services, reason: 'Execute fixed-demo topology verification' }); checking.value = false; if (!response.success) { verificationError.value = response.message || '固定拓扑校验请求失败'; ElMessage.error(verificationError.value); return; } verificationResult.value = response.data; ElMessage[response.data?.valid ? 'success' : 'error'](response.data?.valid ? '固定拓扑校验通过（fixed-demo）' : '固定拓扑校验未通过'); }
load();
</script>
<style scoped>.verification-result{margin-top:14px}</style>
