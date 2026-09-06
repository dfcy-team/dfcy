<template>
  <AppPage
    eyebrow=""
    title="治理中心"
    subtitle="统一查看 API 合同和助手治理对象；所有实际检查与评估仍在对应详情页发起。"
    boundary-note="治理中心只展示当前租户可见的真实服务端数据。API 检查仅为 mock 合同校验；真实助手评估只允许在助手详情使用合成或公开测试数据发起。"
    :capability="capability"
  >
    <template #action>
      <el-button :loading="state === 'loading'" @click="load">刷新</el-button>
    </template>

    <GovernancePilotJourney :active-step="0" />

    <AppState v-if="state === 'loading'" status="loading" />
    <AppState v-else-if="state === 'forbidden'" status="forbidden" detail="当前账号没有治理中心查看权限。" />
    <template v-else>
      <el-alert
        v-if="state === 'partial'"
        class="source-alert"
        type="warning"
        :closable="false"
        show-icon
        title="部分治理数据读取失败"
        description="失败的数据源已按 fail-closed 处理，不显示估算数量、默认状态或本地样例。请刷新或检查服务端权限。"
      />
      <el-alert
        v-else-if="state === 'error'"
        class="source-alert"
        type="error"
        :closable="false"
        show-icon
        title="治理数据读取失败"
        description="服务端没有返回可安全展示的数据，已停止显示治理对象摘要。"
      />

      <section class="management-section" aria-labelledby="governance-objects-title">
        <div class="section-heading">
          <div>
            <h2 id="governance-objects-title">治理对象</h2>
            <p>开放式管理入口；数量和最近状态仅来自真实 API 列表响应。</p>
          </div>
          <span class="section-note">实际动作在详情页</span>
        </div>

        <div class="management-table" role="table" aria-label="治理对象列表">
          <div class="management-row management-row--head" role="row">
            <span role="columnheader">对象</span>
            <span role="columnheader">当前数量</span>
            <span role="columnheader">最近状态</span>
            <span role="columnheader">说明</span>
            <span role="columnheader">入口</span>
          </div>
          <div v-for="source in sources" :key="source.key" class="management-row" role="row">
            <div class="object-name" role="cell">
              <strong>{{ source.label }}</strong>
              <small>{{ source.scope }}</small>
            </div>
            <span role="cell" class="object-value">{{ displayCount(source.count) }}</span>
            <span role="cell" :class="['object-status', { 'object-status--error': source.error }]">{{ source.status }}</span>
            <span role="cell" class="object-description">{{ source.description }}</span>
            <div role="cell" class="object-action">
              <button
                v-if="source.allowed"
                type="button"
                class="text-action"
                :disabled="Boolean(source.error)"
                @click="openResource(source.path)"
              >
                查看详情
              </button>
              <span v-else class="text-action text-action--disabled" aria-disabled="true">无查看权限</span>
            </div>
            <span v-if="source.error" class="source-error" role="alert">{{ source.error }}</span>
          </div>
        </div>
      </section>

      <section class="operating-boundary" aria-labelledby="governance-boundary-title">
        <h2 id="governance-boundary-title">操作边界</h2>
        <dl>
          <div><dt>助手评估</dt><dd>在助手详情发起真实异步评估，服务端执行租户、数据级别和审计校验。</dd></div>
          <div><dt>API 检查</dt><dd>仅执行固定的 <code>fixed-demo/mock</code> 合同结构校验，不代表运行时联通性。</dd></div>
          <div><dt>凭据处理</dt><dd>本页面不接收、不展示、不保存 API key、密码、Cookie 或真实业务数据。</dd></div>
        </dl>
      </section>
    </template>
  </AppPage>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import GovernancePilotJourney from '../../components/GovernancePilotJourney.vue';
import { fetchApiContracts, fetchAssistants } from '../../api/governance';
import { useAuthStore } from '../../stores/auth';

const router = useRouter();
const auth = useAuthStore();
const state = ref('loading');
const capability = ref('pending');

const sources = reactive([
  {
    key: 'api-contracts',
    label: 'API 合同',
    scope: '接口路径、权限与版本',
    description: '核对合同结构；检查动作仅为 mock 校验。',
    path: '/governance/api-contracts',
    permission: 'governance.api.view',
    allowed: false,
    count: null,
    status: '未读取',
    error: ''
  },
  {
    key: 'assistants',
    label: '助手治理',
    scope: '版本、数据级别与评估历史',
    description: '真实评估在助手详情发起，结果由服务端返回。',
    path: '/governance/assistants',
    permission: 'governance.assistants.view',
    allowed: false,
    count: null,
    status: '未读取',
    error: ''
  }
]);

const allowedSources = computed(() => sources.filter((source) => source.allowed));

function resetSource(source) {
  source.allowed = auth.isInternal && (auth.isSuperuser || auth.hasPermission(source.permission));
  source.count = null;
  source.status = source.allowed ? '读取中' : '无查看权限';
  source.error = '';
}

function parsePayload(payload) {
  const rows = Array.isArray(payload?.results) ? payload.results : (Array.isArray(payload) ? payload : []);
  const rawCount = payload && !Array.isArray(payload) ? payload.count : undefined;
  const count = rawCount === undefined || rawCount === null || rawCount === '' || !Number.isFinite(Number(rawCount)) ? null : Number(rawCount);
  const status = payload?.latest_status || payload?.status || rows[0]?.status || (count === 0 ? '暂无记录' : '—');
  return { count, status };
}

function applyResponse(source, response) {
  if (!response?.success) {
    source.count = null;
    source.status = '读取失败';
    source.error = response?.message || '服务端数据读取失败';
    return false;
  }
  const parsed = parsePayload(response.data);
  source.count = parsed.count;
  source.status = parsed.status;
  return true;
}

async function load() {
  state.value = 'loading';
  capability.value = 'pending';
  sources.forEach(resetSource);
  if (!allowedSources.value.length) {
    state.value = 'forbidden';
    capability.value = 'disabled';
    return;
  }

  const requests = sources.map((source) => {
    if (!source.allowed) return Promise.resolve({ source, response: null, skipped: true });
    const request = source.key === 'api-contracts'
      ? fetchApiContracts({ page: 1, page_size: 1 })
      : fetchAssistants({ page: 1, page_size: 1 });
    return request.then((response) => ({ source, response, skipped: false }));
  });
  const results = await Promise.all(requests);
  const requestedResults = results.filter((item) => !item.skipped);
  const successes = requestedResults.filter((item) => applyResponse(item.source, item.response));
  const failures = requestedResults.length - successes.length;
  if (!successes.length) {
    state.value = 'error';
    capability.value = 'degraded';
  } else if (failures) {
    state.value = 'partial';
    capability.value = 'degraded';
  } else {
    state.value = 'ready';
    capability.value = results.find((item) => item.response?.data?.api_status)?.response.data.api_status || 'connected';
  }
}

function displayCount(value) {
  return value === null || value === undefined ? '—' : String(value);
}

function openResource(path) {
  const source = sources.find((item) => item.path === path);
  if (!source?.allowed || source.error) return;
  router.push(path);
}

load();
</script>

<style scoped>
.source-alert { margin-bottom: 16px; }
.management-section { margin-top: 2px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 10px; }
.section-heading h2, .operating-boundary h2 { margin: 0; color: #172033; font-size: 16px; }
.section-heading p { margin: 5px 0 0; color: #64748b; font-size: 13px; }
.section-note { color: #64748b; font-size: 12px; }
.management-table { border-top: 1px solid #cfd8e3; border-bottom: 1px solid #cfd8e3; background: #fff; }
.management-row { display: grid; grid-template-columns: minmax(150px, 1.2fr) 100px 120px minmax(220px, 2fr) 110px; gap: 14px; align-items: center; position: relative; min-height: 72px; padding: 12px 14px; border-top: 1px solid #e7edf4; }
.management-row:first-child { border-top: 0; }
.management-row--head { min-height: 42px; border-top: 0; background: #f8fafc; color: #64748b; font-size: 12px; }
.object-name { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.object-name strong { color: #172033; font-size: 14px; font-weight: 650; }
.object-name small, .object-description { color: #64748b; font-size: 12px; line-height: 1.45; }
.object-value { color: #172033; font-variant-numeric: tabular-nums; }
.object-status { color: #166534; font-size: 13px; }
.object-status--error { color: #b42318; }
.text-action { padding: 0; border: 0; background: transparent; color: #1d4ed8; font: inherit; font-size: 13px; cursor: pointer; }
.text-action:disabled { color: #94a3b8; cursor: not-allowed; }
.text-action:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
.text-action--disabled { color: #94a3b8; cursor: not-allowed; }
.source-error { grid-column: 1 / -1; margin-top: -5px; color: #b42318; font-size: 12px; }
.operating-boundary { margin-top: 24px; padding-top: 16px; border-top: 1px solid #dbe3ec; }
.operating-boundary dl { margin: 10px 0 0; }
.operating-boundary dl > div { display: grid; grid-template-columns: 100px 1fr; gap: 14px; padding: 9px 0; border-top: 1px solid #edf1f5; }
.operating-boundary dt { color: #475569; font-size: 13px; font-weight: 650; }
.operating-boundary dd { margin: 0; color: #64748b; font-size: 13px; line-height: 1.5; }
code { color: #172033; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
@media (max-width: 900px) { .management-row { grid-template-columns: minmax(150px, 1fr) 80px 110px minmax(160px, 1.5fr) 100px; gap: 10px; } }
@media (max-width: 720px) { .section-heading { align-items: flex-start; flex-direction: column; gap: 4px; } .management-table { border-bottom: 0; } .management-row--head { display: none; } .management-row { grid-template-columns: 1fr 80px; gap: 8px 14px; padding: 14px 4px; } .object-name { grid-column: 1 / 2; } .object-value { grid-column: 2 / 3; justify-self: end; } .object-status, .object-description { grid-column: 1 / -1; } .object-action { grid-column: 1 / -1; } .source-error { grid-column: 1 / -1; } .operating-boundary dl > div { grid-template-columns: 1fr; gap: 4px; } }
</style>
