<template>
  <AppPage
    eyebrow=""
    title="验证中心"
    subtitle="聚合专项安全评审、受控验证和性能验证，形成进入准入决策前的真实证据。"
    boundary-note="所有数量、状态和证据均来自服务端真实列表。性能验证会产生真实负载，只能在已批准的详情上下文内执行。"
    :capability="capability"
  >
    <template #action><el-button :loading="state === 'loading'" @click="load">刷新</el-button></template>

    <GovernancePilotJourney :active-step="1" />

    <AppState v-if="state === 'loading'" status="loading" />
    <AppState v-else-if="state === 'forbidden'" status="forbidden" detail="当前账号没有验证中心查看权限。" />
    <template v-else>
      <el-alert
        v-if="state === 'partial'"
        class="source-alert"
        type="warning"
        :closable="false"
        show-icon
        title="部分验证数据读取失败"
        description="失败的数据源已按 fail-closed 处理，不显示估算数量、默认状态或本地样例。"
      />
      <el-alert
        v-else-if="state === 'error'"
        class="source-alert"
        type="error"
        :closable="false"
        show-icon
        title="验证数据读取失败"
        description="服务端没有返回可安全展示的数据，已停止显示验证摘要。"
      />

      <section class="validation-section" aria-labelledby="validation-jobs-title">
        <div class="section-heading">
          <div>
            <h2 id="validation-jobs-title">验证工作入口</h2>
            <p>点击后进入原有工作台或详情页；创建、审批、执行和结果提交不在聚合页完成。</p>
          </div>
          <span class="section-note">真实证据优先</span>
        </div>

        <div class="validation-table" role="table" aria-label="验证工作入口列表">
          <div class="validation-row validation-row--head" role="row">
            <span role="columnheader">工作类型</span>
            <span role="columnheader">当前数量</span>
            <span role="columnheader">最近状态</span>
            <span role="columnheader">生产边界</span>
            <span role="columnheader">入口</span>
          </div>
          <div v-for="source in sources" :key="source.key" class="validation-row" role="row">
            <div class="validation-name" role="cell">
              <strong>{{ source.label }}</strong>
              <small>{{ source.scope }}</small>
            </div>
            <span role="cell" class="validation-value">{{ displayCount(source.count) }}</span>
            <span role="cell" :class="['validation-status', { 'validation-status--error': source.error }]">{{ source.status }}</span>
            <span role="cell" class="validation-description">{{ source.description }}</span>
            <div role="cell" class="validation-action">
              <button
                v-if="source.allowed"
                type="button"
                class="text-action"
                :disabled="Boolean(source.error)"
                @click="openResource(source.path)"
              >
                查看工作台
              </button>
              <span v-else class="text-action text-action--disabled" aria-disabled="true">无查看权限</span>
            </div>
            <span v-if="source.error" class="source-error" role="alert">{{ source.error }}</span>
          </div>
        </div>
      </section>

      <section class="validation-boundary" aria-labelledby="validation-boundary-title">
        <h2 id="validation-boundary-title">执行边界</h2>
        <dl>
          <div><dt>安全评审</dt><dd>按服务端策略、审批和审计链记录风险评审结果。</dd></div>
          <div><dt>受控验证</dt><dd>仅允许受控目标与合成或脱敏数据，结果必须从详情入口提交。</dd></div>
          <div><dt>性能验证</dt><dd>执行会对受控目标产生真实负载；执行权限和确认逻辑仍由详情工作台与服务端共同校验。</dd></div>
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
import { fetchP8Resources } from '../../api/pilot';
import { useAuthStore } from '../../stores/auth';

const router = useRouter();
const auth = useAuthStore();
const state = ref('loading');
const capability = ref('pending');

const sources = reactive([
  {
    key: 'security',
    label: '专项安全评审',
    scope: '风险、范围与人工评审',
    description: '形成安全门禁证据，不直接改变生产状态。',
    path: '/pilot/security-reviews',
    permission: 'pilot.security_review.view',
    allowed: false,
    count: null,
    status: '未读取',
    error: ''
  },
  {
    key: 'verification',
    label: '受控验证',
    scope: '受控目标与成功标准',
    description: '验证结果从详情工作台提交并进入审计链。',
    path: '/pilot/verification-runs',
    permission: 'pilot.verification.view',
    allowed: false,
    count: null,
    status: '未读取',
    error: ''
  },
  {
    key: 'performance',
    label: '性能验证',
    scope: '负载、延迟与资源阈值',
    description: '性能作业会产生真实负载，执行前必须确认目标和窗口。',
    path: '/pilot/performance-runs',
    permission: 'pilot.performance.view',
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
    return fetchP8Resources(source.key, { page: 1, page_size: 1 }).then((response) => ({ source, response, skipped: false }));
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
.validation-section { margin-top: 2px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 10px; }
.section-heading h2, .validation-boundary h2 { margin: 0; color: #172033; font-size: 16px; }
.section-heading p { margin: 5px 0 0; color: #64748b; font-size: 13px; }
.section-note { color: #64748b; font-size: 12px; }
.validation-table { border-top: 1px solid #cfd8e3; border-bottom: 1px solid #cfd8e3; background: #fff; }
.validation-row { display: grid; grid-template-columns: minmax(150px, 1.2fr) 100px 120px minmax(220px, 2fr) 120px; gap: 14px; align-items: center; position: relative; min-height: 72px; padding: 12px 14px; border-top: 1px solid #e7edf4; }
.validation-row:first-child { border-top: 0; }
.validation-row--head { min-height: 42px; border-top: 0; background: #f8fafc; color: #64748b; font-size: 12px; }
.validation-name { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.validation-name strong { color: #172033; font-size: 14px; font-weight: 650; }
.validation-name small, .validation-description { color: #64748b; font-size: 12px; line-height: 1.45; }
.validation-value { color: #172033; font-variant-numeric: tabular-nums; }
.validation-status { color: #166534; font-size: 13px; }
.validation-status--error { color: #b42318; }
.text-action { padding: 0; border: 0; background: transparent; color: #1d4ed8; font: inherit; font-size: 13px; cursor: pointer; }
.text-action:disabled { color: #94a3b8; cursor: not-allowed; }
.text-action:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
.text-action--disabled { color: #94a3b8; cursor: not-allowed; }
.source-error { grid-column: 1 / -1; margin-top: -5px; color: #b42318; font-size: 12px; }
.validation-boundary { margin-top: 24px; padding-top: 16px; border-top: 1px solid #dbe3ec; }
.validation-boundary dl { margin: 10px 0 0; }
.validation-boundary dl > div { display: grid; grid-template-columns: 100px 1fr; gap: 14px; padding: 9px 0; border-top: 1px solid #edf1f5; }
.validation-boundary dt { color: #475569; font-size: 13px; font-weight: 650; }
.validation-boundary dd { margin: 0; color: #64748b; font-size: 13px; line-height: 1.5; }
@media (max-width: 900px) { .validation-row { grid-template-columns: minmax(150px, 1fr) 80px 110px minmax(160px, 1.5fr) 100px; gap: 10px; } }
@media (max-width: 720px) { .section-heading { align-items: flex-start; flex-direction: column; gap: 4px; } .validation-table { border-bottom: 0; } .validation-row--head { display: none; } .validation-row { grid-template-columns: 1fr 80px; gap: 8px 14px; padding: 14px 4px; } .validation-name { grid-column: 1 / 2; } .validation-value { grid-column: 2 / 3; justify-self: end; } .validation-status, .validation-description, .validation-action { grid-column: 1 / -1; } .source-error { grid-column: 1 / -1; } .validation-boundary dl > div { grid-template-columns: 1fr; gap: 4px; } }
</style>
