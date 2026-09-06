<template>
  <AppPage
    eyebrow=""
    title="运维控制台"
    subtitle="汇总准入门禁、当前阻断项和部署、恢复、回滚、性能作业状态。"
    boundary-note="控制台只读取服务端实时状态；每项执行仍需在对应工作台按权限、版本和审批规则发起。"
    :capability="capability"
  >
    <template #action><el-button :loading="state === 'loading'" @click="load">刷新状态</el-button></template>
    <GovernancePilotJourney :active-step="4" />
    <AppState v-if="state !== 'ready'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <el-alert
        v-if="!canViewControlRoom"
        class="control-scope-alert"
        type="info"
        :closable="false"
        show-icon
        title="当前账号仅能访问下方已授权的运维入口"
        description="实时门禁、阻断项与执行作业需要试点控制台查看权限，未授权数据不会发起请求或在前端推测。"
      />
      <section v-if="canViewControlRoom" class="summary-band" aria-label="试点摘要">
        <div><span>环境</span><strong>{{ data.environment }}</strong></div>
        <div><span>准入状态</span><strong>{{ data.readiness_status }}</strong></div>
        <div><span>证据评分</span><strong>{{ data.readiness_score ?? '--' }}</strong></div>
        <div><span>活动作业</span><strong>{{ activeExecutionCount }}</strong></div>
      </section>
      <section class="control-entry-section" aria-labelledby="control-entry-title">
        <div class="section-heading"><h2 id="control-entry-title">运维入口</h2><span>仅打开真实服务端工作台</span></div>
        <div class="control-entry-list">
          <template v-for="entry in controlEntries" :key="entry.path">
            <router-link v-if="canOpen(entry)" class="control-entry" :to="entry.path">
              <strong>{{ entry.label }}</strong><span>{{ entry.description }}</span>
            </router-link>
            <span v-else class="control-entry control-entry--disabled" aria-disabled="true">
              <strong>{{ entry.label }}</strong><span>当前账号无查看权限</span>
            </span>
          </template>
        </div>
      </section>
      <div v-if="canViewControlRoom" class="workspace-grid">
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
      <section v-if="canViewControlRoom" id="execution-jobs" class="execution-section">
        <div class="section-heading"><h2>执行作业</h2><span>queued / running / passed / failed</span></div>
        <el-table :data="data.executions" border empty-text="暂无执行作业">
          <el-table-column prop="id" label="作业 ID" min-width="180" />
          <el-table-column prop="operation" label="操作" min-width="140" />
          <el-table-column prop="target" label="目标" min-width="160" />
          <el-table-column prop="status" label="状态" width="120" />
          <el-table-column prop="updated_at" label="更新时间" min-width="180" />
          <el-table-column label="指标 / 阈值" min-width="240"><template #default="{ row }"><pre>{{ JSON.stringify(row.result_metrics || row.metrics || row.thresholds || {}, null, 2) }}</pre></template></el-table-column>
          <el-table-column prop="error_message" label="失败信息" min-width="200" />
        </el-table>
      </section>
    </template>
  </AppPage>
</template>

<script setup>
import { computed, ref } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import GovernancePilotJourney from '../../components/GovernancePilotJourney.vue';
import { fetchExecutions, fetchPilotControlRoom } from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';
import { statusFromApiResponse } from '../../utils/uiState';

const state = ref('loading');
const capability = ref('connected');
const errorMessage = ref('');
const data = ref({ gate_summary: [], blockers: [], executions: [] });
const auth = useAuthStore();
// The aggregate workbench is routable when an operator can view any of its
// scoped entries. Only control.view authorizes the control-room summary and
// execution collection; topology/capacity-only operators must not trigger
// those broader API reads.
const canOpenControlRoom = computed(() => auth.isInternal && (
  auth.isSuperuser
  || auth.hasPermission('pilot.control.view')
  || auth.hasPermission('pilot.topology.view')
  || auth.hasPermission('pilot.capacity.view')
));
const canViewControlRoom = computed(() => auth.isSuperuser || auth.hasPermission('pilot.control.view'));
const controlEntries = [
  { label: '拓扑', description: '查看受控部署拓扑与网络边界', path: '/pilot/topology', permissions: ['pilot.topology.view'] },
  { label: '容量', description: '查看实时容量证据与有效期', path: '/pilot/capacity', permissions: ['pilot.capacity.view'] },
  { label: '执行作业', description: '查看当前作业与实时状态', path: '/pilot/control-room#execution-jobs', permissions: ['pilot.control.view'] },
  { label: '证据审计', description: '查看操作日志和审计引用', path: '/audit/operations', permissions: ['audit.operation_logs.view'] }
];
function canOpen(entry) { return auth.isInternal && (auth.isSuperuser || entry.permissions.some((permission) => auth.hasPermission(permission))); }
const activeExecutionCount = computed(() => (data.value.executions || []).filter((item) => ['queued', 'running', 'pending', 'in_progress'].includes(item.status || item.state)).length);

async function load() {
  state.value = 'loading';
  errorMessage.value = '';
  if (!canOpenControlRoom.value) {
    data.value = { gate_summary: [], blockers: [], executions: [] };
    capability.value = 'disabled';
    state.value = 'forbidden';
    errorMessage.value = '当前账号没有运维控制台查看权限。';
    return;
  }
  if (!canViewControlRoom.value) {
    data.value = { gate_summary: [], blockers: [], executions: [] };
    capability.value = 'pending';
    state.value = 'ready';
    return;
  }
  const [controlRoomResponse, executionsResponse] = await Promise.all([
    fetchPilotControlRoom({ environment: 'pilot' }),
    // The execution collection is already tenant/scope filtered server-side;
    // its strict contract accepts pagination and execution filters, not an
    // environment parameter.
    fetchExecutions({ page: 1, page_size: 100 })
  ]);
  if (!controlRoomResponse.success) {
    state.value = statusFromApiResponse(controlRoomResponse, typeof navigator === 'undefined' || navigator.onLine);
    errorMessage.value = controlRoomResponse.message || '控制台状态读取失败';
    return;
  }
  if (!executionsResponse.success) {
    state.value = statusFromApiResponse(executionsResponse, typeof navigator === 'undefined' || navigator.onLine);
    errorMessage.value = executionsResponse.message || '执行作业读取失败';
    return;
  }
  data.value = { ...(controlRoomResponse.data || {}), executions: executionsResponse.data?.results || executionsResponse.data?.executions || [] };
  capability.value = controlRoomResponse.data?.api_status || executionsResponse.data?.api_status || 'connected';
  state.value = 'ready';
}
load();
</script>

<style scoped>
.summary-band { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 20px; border: 1px solid #d9e1ea; background: #d9e1ea; }
.control-scope-alert { margin-bottom: 18px; }
.summary-band div { padding: 16px; background: #fff; }
.summary-band span { display: block; color: #687386; font-size: 12px; }
.summary-band strong { display: block; margin-top: 6px; font-size: 18px; }
.control-entry-section { margin-bottom: 22px; padding-top: 2px; }
.control-entry-list { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-top: 10px; border: 1px solid #d9e1ea; background: #d9e1ea; }
.control-entry { display: flex; flex-direction: column; gap: 5px; min-height: 76px; padding: 14px; background: #fff; color: #1d4ed8; }
.control-entry strong { color: inherit; font-size: 14px; font-weight: 650; }
.control-entry span { color: #64748b; font-size: 12px; line-height: 1.45; }
.control-entry--disabled { color: #94a3b8; cursor: not-allowed; }
.workspace-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.execution-section { margin-top: 22px; }
.section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.section-heading span { color: #64748b; font-size: 12px; }
h2 { font-size: 15px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.4 ui-monospace, monospace; }
@media (max-width: 900px) { .summary-band, .workspace-grid { grid-template-columns: 1fr; } .control-entry-list { grid-template-columns: repeat(2, minmax(0, 1fr)); } .section-heading { align-items: flex-start; flex-direction: column; } }
@media (max-width: 720px) { .control-entry-list { grid-template-columns: 1fr; } }
</style>
