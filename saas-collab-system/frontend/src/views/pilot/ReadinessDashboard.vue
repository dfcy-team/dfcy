<template>
  <AppPage eyebrow="CONTROLLED PILOT" title="试点准入" subtitle="汇总代码、CI、安全、数据库、网络、恢复、回滚与容量证据。" boundary-note="准入证据仅用于决策；本页不执行部署、备份恢复、数据库或平台操作。" :capability="capability">
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <section class="summary"><span>环境</span><strong>{{ data.environment_id }}</strong><span>总体状态</span><strong>{{ data.overall_status }}</strong></section>
      <el-table :data="data.gates" border>
        <el-table-column prop="gate_code" label="门禁" width="130" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="证据引用" min-width="200"><template #default="{ row }">{{ (row.evidence_refs || []).join(', ') }}</template></el-table-column>
        <el-table-column prop="owner" label="责任人" width="130" />
        <el-table-column prop="expires_at" label="有效期" min-width="180" />
      </el-table>
    </template>
  </AppPage>
</template>
<script setup>
import { ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchPilotReadiness } from '../../api/pilot';
import { statusFromApiResponse } from '../../utils/uiState';
const state = ref('loading'); const capability = ref('pending'); const errorMessage = ref(''); const data = ref({ gates: [] });
async function load() { state.value = 'loading'; const response = await fetchPilotReadiness({ environment_id: 'controlled-pilot' }); if (!response.success) { state.value = statusFromApiResponse(response, navigator.onLine); errorMessage.value = response.message; return; } data.value = response.data; capability.value = response.data.api_status || 'sandbox'; state.value = 'ready'; }
load();
</script>
<style scoped>.summary{display:grid;grid-template-columns:120px 1fr 120px 1fr;gap:1px;margin-bottom:14px;border:1px solid #dbe3ec;background:#dbe3ec}.summary>*{padding:14px;background:#fff}.summary span{color:#64748b}.summary strong{color:#172033}@media(max-width:700px){.summary{grid-template-columns:110px 1fr}}</style>
