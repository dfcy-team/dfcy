<template>
  <AppPage
    eyebrow="UI-P8 / CONTROLLED PILOT"
    title="生产试点控制台"
    subtitle="聚合脱敏准入证据、阻断项和过期状态，不执行部署或平台连接。"
    boundary-note="控制台仅展示计划与证据状态；ready/go 不等于已部署、已连接生产平台或已获生产发布授权。"
    :capability="capability"
  >
    <template #action><el-button :loading="state === 'loading'" @click="load">刷新证据</el-button></template>
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <section class="summary-band">
        <div><span>环境</span><strong>{{ data.environment }}</strong></div>
        <div><span>准入状态</span><strong>{{ data.readiness_status }}</strong></div>
        <div><span>证据评分</span><strong>{{ data.readiness_score ?? '--' }}</strong></div>
        <div><span>合同版本</span><strong>{{ data.contract_version }}</strong></div>
      </section>
      <div class="workspace-grid">
        <section>
          <h2>门禁状态</h2>
          <el-table :data="data.gate_summary" border empty-text="暂无可用门禁证据">
            <el-table-column prop="name" label="门禁" min-width="180" />
            <el-table-column prop="status" label="状态" width="130" />
            <el-table-column prop="source_type" label="来源" min-width="150" />
          </el-table>
        </section>
        <section>
          <h2>当前阻断项</h2>
          <el-table :data="data.blockers" border empty-text="暂无阻断项">
            <el-table-column prop="code" label="代码" min-width="160" />
            <el-table-column prop="message" label="说明" min-width="260" />
          </el-table>
        </section>
      </div>
    </template>
  </AppPage>
</template>

<script setup>
import { ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { fetchPilotControlRoom } from '../../api/pilot';
import { statusFromApiResponse } from '../../utils/uiState';

const state = ref('loading');
const capability = ref('pending');
const errorMessage = ref('');
const data = ref({ gate_summary: [], blockers: [] });

async function load() {
  state.value = 'loading';
  const response = await fetchPilotControlRoom({ environment: 'pilot' });
  if (!response.success) {
    state.value = statusFromApiResponse(response, navigator.onLine);
    errorMessage.value = response.message;
    return;
  }
  data.value = response.data;
  capability.value = response.data.api_status || 'pending';
  state.value = 'ready';
}
load();
</script>

<style scoped>
.summary-band { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 20px; border: 1px solid #d9e1ea; background: #d9e1ea; }
.summary-band div { padding: 16px; background: #fff; }
.summary-band span { display: block; color: #687386; font-size: 12px; }
.summary-band strong { display: block; margin-top: 6px; font-size: 18px; }
.workspace-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
h2 { font-size: 15px; }
@media (max-width: 900px) { .summary-band, .workspace-grid { grid-template-columns: 1fr; } }
</style>
