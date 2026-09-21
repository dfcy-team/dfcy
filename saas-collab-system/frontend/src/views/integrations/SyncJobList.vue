<template>
  <AppPage
    eyebrow="API DATA INTEGRATION"
    title="同步任务"
    subtitle="查看内部同步调度、任务健康和最近一次运行结果。"
    boundary-note="启用任务不会立即执行；点击“执行一次真实同步”后，仅读取平台数据并写入本地数据库，不修改平台商品、价格或库存。提交不代表成功，请查看运行记录。模拟运行仅限独立 Mock 任务。"
    :capability="capability"
  >
    <template #action>
      <el-button v-if="auth.hasPermission('integrations.manage')" type="primary" @click="createOpen = true">创建同步任务</el-button>
      <el-button v-if="auth.hasPermission('integrations.manage')" @click="previewOpen = true">检查缺失任务</el-button>
      <el-button plain @click="router.push('/integrations/sync-runs')">查看运行记录</el-button>
      <el-button plain :loading="loading" @click="load">刷新</el-button>
    </template>


    <p class="scheduler-health">调度心跳：{{ { recent: '最近已观测到', stale: '已超时，请检查调度服务', unknown: '未观测到，请检查调度服务' }[scheduler.heartbeat_state] || '未观测到' }} · {{ syncTime(scheduler.last_seen_at) }} UTC。心跳不代表队列消费者或同步执行成功。</p>
    <el-form inline class="task-filters" label-position="top">
      <el-form-item label="平台"><el-select v-model="filters.platforms" placeholder="全部平台" multiple collapse-tags collapse-tags-tooltip filterable clearable @change="search"><el-option v-for="value in options.platforms || []" :key="value" :value="value" :label="value" /></el-select></el-form-item>
      <el-form-item label="店铺／仓库"><el-select v-model="filters.subjects" placeholder="全部店铺／仓库" multiple collapse-tags collapse-tags-tooltip filterable clearable @change="search"><el-option v-for="item in options.subjects || []" :key="item.value" :value="item.value" :label="item.label" /></el-select></el-form-item>
      <el-form-item label="同步内容"><el-select v-model="filters.resource" placeholder="全部同步内容" clearable @change="search"><el-option v-for="value in options.resource_types || []" :key="value" :value="value" :label="resourceLabel(value)" /></el-select></el-form-item>
      <el-form-item label="启停状态"><el-select v-model="filters.enabled" placeholder="全部状态" clearable @change="search"><el-option label="启用" value="enabled" /><el-option label="停用" value="disabled" /></el-select></el-form-item>
      <el-form-item label="调度方式"><el-select v-model="filters.schedule" placeholder="全部调度方式" clearable @change="search"><el-option v-for="(label, value) in schedules" :key="value" :value="value" :label="label" /></el-select></el-form-item>
      <el-form-item label="运行健康"><el-select v-model="filters.health" placeholder="全部健康状态" clearable @change="search"><el-option v-for="value in ['healthy','failed','running','authorization','configuration','capability','disabled']" :key="value" :value="value" :label="stateLabel(value)" /></el-select></el-form-item>
    </el-form>
    <AppState v-if="state !== 'ready' && state !== 'empty'" :status="state" :detail="errorMessage" @action="load" />
    <template v-else>
      <section class="sync-summary" aria-label="同步任务健康摘要">
        <header class="summary-heading"><span>任务与运行概况</span><small>当前权限范围 · 不随列表筛选变化</small></header>
        <article v-for="item in summaryItems" :key="item.key" :class="['summary-card', item.value > 0 ? item.tone : '']">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <el-alert
        v-if="productSyncContext"
        class="product-sync-context"
        type="info"
        show-icon
        :closable="false"
        :title="`当前查看：${contextStoreLabel} · 平台商品同步任务`"
      >
        <template #default>
          <span>任务和同步异常已按店铺范围过滤；如果尚未创建商品只读任务，请先在该店铺 API 接入抽屉完成授权、PRODUCT 只读能力校验后创建。</span>
          <el-button
            v-if="canOpenStoreApiConfig"
            link
            type="primary"
            class="context-action"
            @click="openStoreApiConfig"
          >去店铺配置并创建商品同步任务</el-button>
        </template>
      </el-alert>

      <el-alert
        title="健康状态与调度状态分开统计；失败、重试等待、重试耗尽和陈旧运行均需人工关注。"
        type="warning"
        show-icon
        :closable="false"
      />

      <div class="incident-link"><span>待处理异常：{{ (summary.open_sync_incident_count || 0) + (summary.acknowledged_sync_incident_count || 0) }}</span><el-button link type="primary" @click="router.push('/integrations/incidents')">前往同步异常</el-button></div>

      <el-empty v-if="state === 'empty'" description="暂无同步任务" />
      <el-table v-else v-loading="loading" :data="rows" border stripe empty-text="暂无同步任务">
        <el-table-column label="任务名称" min-width="190"><template #default="{ row }">{{ resourceLabel(row.resource_type) }}同步 #{{ row.id }}</template></el-table-column>
        <el-table-column prop="platform" label="平台" min-width="110" />
        <el-table-column prop="subject_name" label="业务主体" min-width="150">
          <template #default="{ row }">
            <div>{{ row.subject_name || '未绑定' }}</div>
            <small>{{ row.subject_code || '-' }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="resource_type" label="资源类型" min-width="150">
          <template #default="{ row }">{{ resourceLabel(row.resource_type) }}</template>
        </el-table-column>
        <el-table-column prop="health_state" label="任务健康" min-width="120">
          <template #default="{ row }">
            <el-tag :type="stateTagType(row.health_state)" effect="plain">{{ stateLabel(row.health_state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="capability_state" label="能力状态" min-width="145">
          <template #default="{ row }">
            <el-tag :type="capabilityTagType(row.capability_state)" effect="plain">{{ capabilityLabel(row.capability_state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启停状态" width="100"><template #default="{ row }">{{ row.is_enabled ? '启用' : '停用' }}</template></el-table-column>
        <el-table-column label="定时规则" min-width="185"><template #default="{ row }">{{ schedules[row.schedule_type] || '—' }}<small v-if="row.schedule_type !== 'manual'" class="schedule-rule">{{ row.schedule_type === 'interval' || row.schedule_type === 'hourly' ? `每 ${row.interval_minutes} 分钟` : `${row.local_time} · ${row.timezone}` }}{{ row.schedule_type === 'weekly' ? ` · 周 ${row.weekdays.join('、')}` : '' }}</small></template></el-table-column>
        <el-table-column label="调度状态" min-width="110"><template #default="{ row }">{{ { disabled: '已停用', paused: '已暂停', queued: '排队中', running: '运行中', retry_waiting: '等待重试', blocked: '配置阻塞', due: '等待派发', scheduled: '等待执行', unscheduled: '未安排', manual: '手动', retry_exhausted: '重试耗尽' }[row.schedule_state] || '—' }}</template></el-table-column>
        <el-table-column label="最近结果" width="110"><template #default="{ row }"><el-button v-if="row.latest_run_pk" link type="primary" @click="viewRuns(row, true)">{{ runStates[row.latest_run_status] || '—' }}</el-button><span v-else>尚未运行</span></template></el-table-column>
        <el-table-column label="最近真实成功（UTC）" min-width="185"><template #default="{ row }">{{ syncTime(row.last_success_at) }}</template></el-table-column>
        <el-table-column prop="blocked_reason" label="阻塞原因" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.blocked_reason || '—' }}<el-button v-if="row.blocked_reason" link type="primary" @click="configRow = row; configOpen = true">检查配置</el-button></template>
        </el-table-column>

        <el-table-column prop="next_run_at" label="下次执行（UTC）" min-width="180">
          <template #default="{ row }">{{ syncTime(row.next_run_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.is_enabled && actionAccess(actionConfigs[2]).visible"
              link type="primary"
              :disabled="actionAccess(actionConfigs[2]).disabled || !!taskBusyReason(row) || !!actionLoading"
              :title="actionAccess(actionConfigs[2]).reason || taskBusyReason(row) || '校验配置并启用，不立即执行'"
              :loading="actionLoading === `enable:${row.id}`"
              @click.stop="runAction(actionConfigs[2], row)"
            >{{ row.schedule_type === 'manual' ? '启用任务' : '启用定时' }}</el-button>
            <el-button
              v-if="['pilot', 'production'].includes(row.environment) && actionAccess(actionConfigs[3]).visible"
              link type="primary"
              :disabled="actionAccess(actionConfigs[3]).disabled || !!liveRunReason(row) || !!actionLoading"
              :title="actionAccess(actionConfigs[3]).reason || liveRunReason(row) || '读取平台数据并写入本地数据库'"
              :loading="actionLoading === `run-live:${row.id}`"
              @click.stop="runAction(actionConfigs[3], row)"
            >执行一次真实同步</el-button>
            <el-button
              v-if="row.environment === 'mock' && actionAccess(actionConfigs[0]).visible"
              link
              type="primary"
              :disabled="actionAccess(actionConfigs[0]).disabled || !!mockRunReason(row) || !!actionLoading"
              :title="actionAccess(actionConfigs[0]).reason || mockRunReason(row)"
              :loading="actionLoading === `${actionConfigs[0].label}:${row.id}`"
              @click.stop="runAction(actionConfigs[0], row)"
            >运行模拟任务</el-button>
            <el-button
              v-if="row.is_enabled && actionAccess(actionConfigs[1]).visible"
              link
              type="danger"
              :disabled="actionAccess(actionConfigs[1]).disabled || !!taskBusyReason(row) || !!actionLoading"
              :title="actionAccess(actionConfigs[1]).reason || taskBusyReason(row)"
              :loading="actionLoading === `${actionConfigs[1].label}:${row.id}`"
              @click.stop="runAction(actionConfigs[1], row)"
            >停用任务</el-button>
            <el-button link type="primary" @click="viewRuns(row)">查看运行记录</el-button>
            <el-button link type="primary" @click="configRow = row; configOpen = true">查看配置</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </template>

    <el-dialog v-model="createOpen" title="创建同步任务" width="min(640px, 94vw)" destroy-on-close :close-on-click-modal="false">
      <CreateSyncJob v-if="createOpen" @created="created" @existing="showExisting" />
    </el-dialog>
    <el-dialog v-model="previewOpen" title="检查缺失任务" width="min(1000px, 94vw)" destroy-on-close>
      <MissingSyncJobsPreview v-if="previewOpen" />
    </el-dialog>
    <el-drawer v-model="configOpen" title="任务配置与定时" size="min(560px, 94vw)">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="任务">#{{ configRow.id }} · {{ resourceLabel(configRow.resource_type) }}</el-descriptions-item>
        <el-descriptions-item label="主体">{{ configRow.subject_name }}</el-descriptions-item>
        <el-descriptions-item label="接入配置">{{ configRow.config_name || '—' }}</el-descriptions-item>
        <el-descriptions-item label="调度方式">{{ schedules[configRow.schedule_type] || '—' }}</el-descriptions-item>
        <el-descriptions-item label="采集范围">
          <template v-if="['sales_order', 'refund_return'].includes(configRow.resource_type)">
            <template v-if="configRow.query_mode === 'range'">
              <template v-if="/^\d{4}-\d{2}-\d{2}$/.test(configRow.range_start_at || '')">{{ configRow.range_start_at }} 至 {{ configRow.range_end_at }}（北京时间，含结束日）</template>
              <template v-else>{{ syncTime(configRow.range_start_at) }} 至 {{ syncTime(configRow.range_end_at) }}（UTC）</template>
            </template>
            <template v-else>每次执行回看最近 {{ configRow.lookback_days ?? 1 }} 天</template>
          </template>
          <template v-else>按资源自身的全量/快照策略采集</template>
        </el-descriptions-item>
        <el-descriptions-item label="最大页数">{{ configRow.max_pages ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="最大记录数">{{ configRow.max_records ?? '—' }}</el-descriptions-item>
      </el-descriptions>
      <el-button @click="openSubjectConfig(configRow)">前往授权配置</el-button>
      <el-button @click="router.push('/integrations/capabilities')">能力矩阵</el-button>
      <el-button @click="router.push('/integrations/production-settings')">只读准入配置</el-button>
      <SyncScheduleSettings :job="configRow" :can-manage="auth.hasPermission('integrations.manage')" @saved="configOpen = false; load()" />
    </el-drawer>
  </AppPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute, useRouter } from 'vue-router';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import CreateSyncJob from '../../components/CreateSyncJob.vue';
import SyncScheduleSettings from '../../components/SyncScheduleSettings.vue';
import { syncTime, syncError, runStates, schedules } from '../../utils/syncPresentation';
import { syncRequestId } from '../../utils/syncRequestId';
import MissingSyncJobsPreview from '../../components/MissingSyncJobsPreview.vue';
import { useMock } from '../../api/request';

import {
  disableSyncJob,
  fetchSyncJobs,
  runSyncJobMock,
  runSyncJob,
  toggleSyncJob
} from '../../api/integrations';
import { useAuthStore } from '../../stores/auth';
import { getActionAccess } from '../../utils/actionAccess';
import { statusFromApiResponse } from '../../utils/uiState';

const actionConfigs = [
  {
    label: 'run-mock',
    permission: 'integrations.run',
    type: 'primary',
    handler: ({ row }) => runSyncJobMock(row.id)
  },
  {
    label: 'disable',
    permission: 'integrations.manage',
    type: 'danger',
    confirmMessage: '停止后续执行，保留已有同步数据和运行记录。',
    handler: ({ row }) => disableSyncJob(row.id)
  },
  {
    label: 'enable', permission: 'integrations.manage',
    confirmMessage: '校验当前配置并启用任务，不立即执行。手动任务需另行点击执行；定时任务仅在调度服务开启后按计划执行。',
    handler: ({ row }) => toggleSyncJob(row.id, true)
  },
  {
    label: 'run-live', permission: 'integrations.run_live_readonly',
    confirmMessage: '将访问真实平台，按任务范围读取数据并写入本地数据库，不修改平台业务数据。提交后请查看运行记录，不要连续提交。',
    handler: ({ row }) => runSyncJob(row.id, liveRunKey(row))
  }
];

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const rows = ref([]);
const createOpen = ref(false), previewOpen = ref(false), configOpen = ref(false), configRow = ref({});
const page = ref(1), total = ref(0), options = ref({});
const filters = reactive({ platforms: [], subjects: [], resource: '', enabled: '', schedule: '', health: '' });
function search() { page.value = 1; load(); }
function viewRuns(row, detail = false) { router.push({ path: '/integrations/sync-runs', query: { sync_job_id: String(row.id), ...(detail ? { detail: String(row.latest_run_pk) } : {}) } }); }
function openSubjectConfig(row) { router.push({ path: row.subject_type === 'warehouse' ? '/master-data/warehouses' : '/master-data/stores', query: { ...(row.store_id ? { store_id: String(row.store_id) } : {}), ...(row.warehouse_id ? { warehouse_id: String(row.warehouse_id) } : {}), panel: 'api' } }); }
function showExisting(id) { createOpen.value = false; Object.assign(filters, { platforms: [], subjects: [], resource: '', enabled: '', schedule: '', health: '' }); router.push({ path: '/integrations/sync-jobs', query: { sync_job_id: String(id) } }); }
function created(id) { ElMessage.success('任务已创建：手动、停用，尚未执行。'); showExisting(id); load(); }
watch(() => route.query, () => { page.value = 1; load(); });

const summary = ref({});
const scheduler = ref({});
const state = ref('loading');
const capability = ref(useMock ? 'mock' : 'pending');
const loading = ref(false);
const actionLoading = ref('');
const errorMessage = ref('');


const productSyncContext = computed(() => String(route.query.resource_type || '') === 'platform_product' && Boolean(route.query.store_id));
const contextStoreLabel = computed(() => String(route.query.subject || route.query.store_name || route.query.store_id || '当前店铺'));
const canOpenStoreApiConfig = computed(() => auth.hasPermission('masterdata.view')
  && auth.hasPermission('integrations.view')
  && auth.hasPermission('integrations.store.view'));

const summaryItems = computed(() => [
  { key: 'job_count', label: '任务总数', value: summary.value.job_count || 0, tone: '' },
  { key: 'failed_run_count', label: '失败运行', value: summary.value.failed_run_count || 0, tone: 'summary-card--danger' },
  { key: 'retry_waiting_job_count', label: '重试等待', value: summary.value.retry_waiting_job_count || 0, tone: 'summary-card--warning' },
  { key: 'retry_exhausted_job_count', label: '重试耗尽', value: summary.value.retry_exhausted_job_count || 0, tone: 'summary-card--danger' },
  { key: 'stale_running_job_count', label: '陈旧运行', value: summary.value.stale_running_job_count || 0, tone: 'summary-card--warning' },
  { key: 'capability_blocked_job_count', label: '能力阻塞', value: summary.value.capability_blocked_job_count || 0, tone: 'summary-card--danger' },
  { key: 'open_sync_alert_count', label: '未关闭预警', value: summary.value.open_sync_alert_count || 0, tone: 'summary-card--warning' },
  { key: 'open_sync_incident_count', label: '待处理事件', value: summary.value.open_sync_incident_count || 0, tone: 'summary-card--danger' },
  { key: 'acknowledged_sync_incident_count', label: '已确认事件', value: summary.value.acknowledged_sync_incident_count || 0, tone: 'summary-card--warning' },
  { key: 'enabled_job_count', label: '启用任务', value: summary.value.enabled_job_count || 0, tone: 'summary-card--success' }
]);

function actionAccess(action) {
  return getActionAccess(auth, action);
}

function responseRows(data) {
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data)) return data;
  return [];
}

function stateLabel(value) {
  return {
    disabled: '已禁用',
    authorization: '授权阻塞',
    configuration: '配置阻塞',
    capability: '能力阻塞',
    running: '运行中',
    failed: '失败',
    due: '待执行',
    healthy: '健康'
  }[value] || value || '-';
}

function resourceLabel(value) {
  return ({
    platform_product: '平台商品',
    sales_order: '销售订单',
    refund_return: '退款退货',
    inventory_snapshot: '库存快照',
    inbound: '入库单',
    shipment: '出库单',
  })[value] || value || '-';
}

function capabilityLabel(value) {
  return {
    not_required: '无需能力',
    ready: '能力就绪',
    authorization: '授权不可用',
    capability_missing: '能力未启用',
    source_not_selected: '未选中来源',
    unsupported: '能力不支持'
  }[value] || value || '-';
}


function stateTagType(value) {
  return {
    healthy: 'success',
    running: 'primary',
    due: 'warning',
    retry_waiting: 'warning',
    retry_exhausted: 'danger',
    failed: 'danger',
    authorization: 'warning',
    configuration: 'warning',
    capability: 'warning',
    disabled: 'info'
  }[value] || 'info';
}

function capabilityTagType(value) {
  return {
    ready: 'success',
    not_required: 'info',
    authorization: 'warning',
    capability_missing: 'danger',
    source_not_selected: 'warning',
    unsupported: 'danger'
  }[value] || 'info';
}

function openStoreApiConfig() {
  if (!productSyncContext.value || !canOpenStoreApiConfig.value) {
    ElMessage.warning('当前角色没有进入店铺 API 配置的权限。');
    return;
  }
  router.push({ path: '/master-data/stores', query: {
    store_id: String(route.query.store_id),
    panel: 'api',
  } });
}

async function load() {
  state.value = 'loading';
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchSyncJobs({
      page: page.value, page_size: 50, subject_key: filters.subjects.join(','), job_state: filters.enabled,
      schedule_type: filters.schedule, health_state: filters.health, sync_job_id: route.query.sync_job_id || '',
      platform: filters.platforms.join(',') || route.query.platform || '',
      api_type: route.query.api_type || '',
      resource_type: filters.resource || route.query.resource_type || '',
      subject: route.query.subject || '',
      ...(route.query.store_id ? { store_id: route.query.store_id } : {}),
    });
    if (!response?.success) {
      state.value = statusFromApiResponse(response, typeof navigator === 'undefined' ? true : navigator.onLine);
      errorMessage.value = response?.message || '同步任务接口请求失败';
      capability.value = response?.http_status ? 'pending' : 'degraded';
      return;
    }
    const data = response.data || {};
    rows.value = responseRows(data);
    summary.value = data.summary || {};
    scheduler.value = data.scheduler || {};
    options.value = data.options || {};
    total.value = data.pagination?.total ?? rows.value.length;
    page.value = data.pagination?.page || page.value;
    const apiStatus = data.api_status || (useMock ? 'mock' : 'pending');
    capability.value = apiStatus === 'fallback' ? 'degraded' : apiStatus;
    state.value = rows.value.length ? 'ready' : 'empty';
  } catch (error) {
    state.value = 'error';
    errorMessage.value = error?.message || '同步任务接口请求失败';
    capability.value = 'degraded';
  } finally {
    loading.value = false;
  }
}

const liveRunKeys = new Map();
function liveRunKey(row) {
  const version = `${row.id}:${row.last_run_at || ''}`;
  if (!liveRunKeys.has(version)) liveRunKeys.set(version, syncRequestId());
  return liveRunKeys.get(version);
}

function taskBusyReason(row) {
  if (!row?.id) return '任务信息不完整，请刷新后重试。';
  return ['queued', 'running'].includes(row.schedule_state) || row.status === 'running'
    ? '任务正在排队或运行，请勿重复提交或切换状态。'
    : '';
}

function liveRunReason(row) {
  if (taskBusyReason(row)) return taskBusyReason(row);
  if (!row.is_enabled || row.status === 'disabled') return '任务已停用，请先启用任务。';
  if (!['pilot', 'production'].includes(row.environment)) return '该任务不是实际平台只读任务。';
  if (row.capability_state && !['ready', 'not_required'].includes(row.capability_state)) return '只读能力未就绪，请检查能力矩阵及授权来源。';
  return row.blocked_reason || '';
}

function mockRunReason(row) {
  if (!row?.id) return '任务信息不完整，请刷新后重试。';
  if (!row.is_enabled || row.status === 'disabled' || row.schedule_state === 'disabled') {
    return '任务已停用，不能运行模拟任务。';
  }
  if (row.environment !== 'mock' || row.resource_type !== 'mock_record') {
    return '仅独立 Mock 任务可运行模拟；真实平台任务请使用受控只读同步入口。';
  }
  if (row.status === 'running' || ['queued', 'running'].includes(row.schedule_state)) return '任务正在排队或运行，请勿重复提交。';
  return '';
}

async function runAction(action, row) {
  const access = actionAccess(action);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  if (action.label === 'run-mock') {
    const reason = mockRunReason(row);
    if (reason) {
      ElMessage.warning(reason);
      return;
    }
  }
  if (actionLoading.value) return;
  const blocked = action.label === 'run-live' ? liveRunReason(row) : taskBusyReason(row);
  if (blocked) { ElMessage.warning(blocked); return; }
  actionLoading.value = `${action.label}:${row.id}`;
  const actionLabel = { disable: '停用任务', enable: '启用任务', 'run-live': '执行一次真实同步', 'run-mock': '运行模拟任务' }[action.label];
  try {
    if (action.confirmMessage) {
      await ElMessageBox.confirm(
        `确认对同步任务“${row.id}”${actionLabel}？${action.confirmMessage}`,
        '同步任务操作确认',
        { type: 'warning' }
      );
    }
    actionLoading.value = `${action.label}:${row.id}`;
    const response = await action.handler({ row, rows: rows.value });
    if (!response?.success) throw new Error(response?.message || `${actionLabel}失败`);
    if (action.label === 'run-live') {
      if (!response.data?.accepted) throw new Error('未获得队列受理确认，请检查运行记录，不要重复提交。');
      ElMessage.success('同步请求已提交队列，不代表同步成功；请查看运行记录，确认任务服务已处理。');
    } else {
      ElMessage.success(action.label === 'enable' ? '任务已启用，尚未执行。' : (action.label === 'run-mock' ? '模拟运行已提交，请查看运行记录。' : `${actionLabel}已完成`));
    }
    await load();
  } catch (error) {
    if (error === 'cancel' || error === 'close') return;
    ElMessage.error(syncError(error?.message) || `${actionLabel}未完成，请刷新并检查运行记录；不要连续提交。`);
  } finally {
    actionLoading.value = '';
  }
}

onMounted(() => {
  load();
});
</script>

<style scoped>
.scheduler-health { margin: 0 0 12px; color: #475569; font-size: 13px; }
.schedule-rule { display: block; margin-top: 4px; }
.task-filters {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 16px;
  padding: 16px;
  margin-bottom: 20px;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}
.task-filters .el-form-item { margin: 0; min-width: 0; }
.task-filters .el-select { width: 100%; }
.task-filters :deep(.el-form-item__label) { margin-bottom: 8px; color: #475569; line-height: 20px; }
.task-filters :deep(.el-select__placeholder) { color: #64748b; }
.incident-link { display: flex; align-items: center; gap: 16px; margin: 12px 0; }

.sync-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 20px;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  overflow: hidden;
  background: #e5eaf0;
}
.summary-heading {
  grid-column: 1 / -1;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px;
  background: #fff;
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}
.summary-heading small { font-weight: 400; }
.summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  min-height: 70px;
  padding: 14px 16px;
  background: #fff;
}
.summary-card span { color: #475569; font-size: 13px; line-height: 20px; }
.summary-card strong { color: #172033; font-size: 24px; line-height: 30px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.summary-card--danger strong { color: #b91c1c; }
.summary-card--warning strong { color: #92400e; }
.summary-card--success strong { color: #047857; }
.product-sync-context { margin-top: 16px; }
.context-action { margin-left: 8px; font-weight: 600; }
small { color: #64748b; font-size: 12px; }



@media (max-width: 1100px) {
  .task-filters { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .summary-card { flex-direction: column; align-items: flex-start; gap: 4px; padding: 12px; }
}

@media (max-width: 680px) {
  .task-filters, .sync-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-filters { gap: 12px; padding: 12px; }
}
</style>
