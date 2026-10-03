<template>
  <section class="report-library">
    <header v-if="tab === 'catalog' || tab === 'saved'"><h1>报表中心</h1><p>选择报表即可查看；保存常用条件，或按需组合分析看板。</p></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="sourceNotice" :title="sourceNotice" type="info" :closable="false" />
    <el-tabs v-model="tab">
      <el-tab-pane label="报表目录" name="catalog">
        <p class="library-hint">按业务模块选择报表。穿透明细仍进入对应的销售、库存或财务页面。</p>
        <div class="catalog"><article v-for="item in datasets" :key="item.id"><el-tag effect="plain">{{ item.module }}</el-tag><h2>{{ item.name }}</h2><p>{{ item.note }}</p><el-button type="primary" plain @click="openDataset(item.id)">查看报表</el-button></article></div>
        <el-empty v-if="!loading && !datasets.length" description="当前账号暂无可用报表，请核对业务权限。" />
        <details v-if="pending.length" class="pending-reports"><summary>待接入报表 · {{ pending.length }} 项</summary><p>以下报表保留规划入口，接入并验收数据后开放查询。</p><el-table :data="pending"><el-table-column prop="name" label="报表" min-width="180" /><el-table-column prop="module" label="归属模块" min-width="140" /><el-table-column prop="reason" label="开放条件" min-width="280" /></el-table></details>
      </el-tab-pane>
      <el-tab-pane label="已保存报表" name="saved">
        <div class="saved-heading"><div><el-button :type="savedScope === 'mine' ? 'primary' : 'default'" @click="savedScope = 'mine'">我的报表</el-button><el-button :type="savedScope === 'shared' ? 'primary' : 'default'" @click="savedScope = 'shared'">团队共享</el-button></div><p>共享配置按查看者的业务权限重新读取数据。</p></div>
        <div v-loading="viewsLoading" class="catalog"><article v-for="view in savedViews" :key="view.id"><h2>{{ view.name }}</h2><p>{{ view.config.kind === 'dashboard' ? `${view.config.module} · 组合看板` : '自助分析' }} · {{ view.is_shared ? '已共享配置' : '个人视图' }}</p><p>更新于 {{ reportTimestamp(view.updated_at) }}（协调世界时）</p><el-button type="primary" plain @click="openView(view)">打开</el-button><el-button v-if="view.is_owner" @click="loadHistory(view)">配置历史</el-button><el-button v-if="view.is_owner" @click="remove(view.id)">删除视图</el-button>
          <div v-if="historyView === view.id" class="history"><el-alert v-if="historyError" :title="historyError" type="error" :closable="false" /><p v-else class="history-note">重新查询会按当前权限读取数据；历史记录保存配置，不是历史完整数据快照。</p><el-table v-if="history.length" :data="history"><el-table-column prop="version" label="版本" width="90"><template #default="scope">版本 {{ scope.row.version }}</template></el-table-column><el-table-column label="动作" width="140"><template #default="scope">{{ historyAction(scope.row.action) }}</template></el-table-column><el-table-column label="时间" min-width="180"><template #default="scope">{{ reportTimestamp(scope.row.created_at) }}（协调世界时）</template></el-table-column><el-table-column label="配置摘要" min-width="220"><template #default="scope">{{ configSummary(scope.row.config) }}</template></el-table-column><el-table-column label="操作" width="130"><template #default="scope"><el-button :disabled="!scope.row.config" @click="reopenHistory(scope.row)">按此配置重查</el-button></template></el-table-column></el-table><el-empty v-else-if="!historyLoading && !historyError" description="暂无配置历史" /></div>
        </article></div>
        <el-empty v-if="!viewsLoading && !savedViews.length" description="当前范围无保存配置；选择报表模板，查询后可保存常用分析。"><el-button type="primary" @click="tab = 'catalog'">选择报表模板</el-button></el-empty>
      </el-tab-pane>
      <el-tab-pane label="自助分析" name="analysis"><ReportWorkbench v-if="tab === 'analysis'" :key="workbenchKey" :catalog="datasets" :view-config="viewConfig" :saved-view="activeSavedView" @saved="loadViews" /></el-tab-pane>
      <el-tab-pane label="组合看板" name="dashboard"><ReportDashboard v-if="tab === 'dashboard'" :key="workbenchKey" :catalog="datasets" :view-config="dashboardConfig" :saved-view="activeSavedView" :module="dashboardModule" :name="viewName" @saved="loadViews" /></el-tab-pane>
    </el-tabs>
  </section>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { reportError, reportTimestamp } from './reportDisplay';
import { useRoute } from 'vue-router';
import { fetchReportDatasets, fetchSavedReportViews, deleteReportView } from '../../api/reporting';
import { fetchReportExceptionSource, fetchReportViewHistory } from '../../api/reportCollaboration';
import ReportWorkbench from './ReportWorkbench.vue';
import ReportDashboard from './ReportDashboard.vue';
import { dashboardModules } from './biDashboard';
import { defaultReportFilters } from './reportContext';
const route = useRoute();
const loading = ref(true), viewsLoading = ref(false), viewsLoaded = ref(false), savedScope = ref('mine'), historyLoading = ref(false);
const tab = ref('catalog'),
  datasets = ref([]),
  pending = ref([]),
  views = ref([]),
  error = ref(''),
  viewConfig = ref(null),
  dashboardConfig = ref(null),
  dashboardModule = ref(dashboardModules.includes(route.query.module) ? route.query.module : '经营分析'),
  viewName = ref(''),
  workbenchKey = ref(0);
const historyView = ref(null), history = ref([]), historyError = ref(''), sourceNotice = ref(''), activeSavedView = ref(null);
let sourceRequest = 0, historyRequest = 0;
const datasetsReady = ref(false);
const savedViews = computed(() => views.value.filter(view => savedScope.value === 'mine' ? view.is_owner : view.is_shared));
async function loadViews() {
  viewsLoading.value = true;
  try {
    const response = await fetchSavedReportViews();
    if (!response.success) throw new Error(response.message);
    views.value = response.data || []; viewsLoaded.value = true;
  } catch (failure) { error.value = reportError(failure.message); }
  finally { viewsLoading.value = false; }
}
watch(tab, value => { if (value === 'saved' && !viewsLoaded.value && !viewsLoading.value) loadViews(); });
function openDataset(id) {
  activeSavedView.value = null;
  const item = datasets.value.find((row) => row.id === id);
  viewConfig.value = { dataset: id, ...item.defaults, filters: defaultReportFilters(item), chart: 'table', pivot: '', ordering: '' };
  workbenchKey.value++;
  tab.value = 'analysis';
}
function openView(view) {
  activeSavedView.value = view;
  if (view.config.kind === 'dashboard') {
    dashboardConfig.value = view.config;
    dashboardModule.value = view.config.module;
    viewName.value = view.name;
  } else viewConfig.value = view.config;
  workbenchKey.value++;
  tab.value = view.config.kind === 'dashboard' ? 'dashboard' : 'analysis';
}
const historyAction = action => ({ create: '创建', update: '更新', archive: '归档', baseline: '迁移登记基线' }[action] || action || '配置变更');
function configSummary(config = {}) {
  if (config.kind === 'dashboard') return `${config.module || '组合看板'} · 组合看板（${config.widgets?.length || 0} 个组件）`;
  const dataset = datasets.value.find(item => item.id === config.dataset);
  const field = key => [...(dataset?.dimensions || []), ...(dataset?.metrics || [])].find(item => item.key === key)?.label || '未识别字段';
  const dims = (config.dimensions || []).map(field), metrics = (config.metrics || []).map(field);
  return [dataset?.name || '报表', dims.length ? `分组：${dims.join('、')}` : '', metrics.length ? `指标：${metrics.join('、')}` : ''].filter(Boolean).join(' · ');
}
async function loadHistory(view) {
  if (!view.is_owner) return;
  const request = ++historyRequest;
  historyView.value = view.id; history.value = []; historyError.value = ''; historyLoading.value = true;
  try {
    const response = await fetchReportViewHistory(view.id);
    if (request !== historyRequest) return;
    if (!response.success) throw new Error(response.message || '历史配置读取失败');
    history.value = response.data || [];
  } catch (failure) { if (request === historyRequest) historyError.value = reportError(failure.message); }
  finally { if (request === historyRequest) historyLoading.value = false; }
}
function reopenHistory(entry) {
  if (!entry.config) return;
  activeSavedView.value = null;
  if (entry.config.kind === 'dashboard') {
    dashboardConfig.value = entry.config;
    dashboardModule.value = entry.config.module;
    viewName.value = entry.name || views.value.find(view => view.id === historyView.value)?.name || '';
    workbenchKey.value++;
    tab.value = 'dashboard';
  } else {
    viewConfig.value = entry.config;
    workbenchKey.value++;
    tab.value = 'analysis';
  }
}
async function loadSource(exceptionId) {
  const request = ++sourceRequest;
  sourceNotice.value = '';
  if (!exceptionId) return;
  activeSavedView.value = null; viewConfig.value = null; workbenchKey.value++;
  try {
    const sourceResponse = await fetchReportExceptionSource(String(exceptionId));
    if (request !== sourceRequest) return;
    if (!sourceResponse.success) throw new Error(sourceResponse.message || '来源核查失败');
    const config = sourceResponse.data?.source?.config;
    if (!config || typeof config !== 'object') throw new Error('来源配置不可用');
    activeSavedView.value = null; viewConfig.value = config; tab.value = 'analysis'; workbenchKey.value++;
    sourceNotice.value = '已载入真实核查来源配置；将按原配置重新查询，不是历史数据快照。';
  } catch (failure) { if (request === sourceRequest) { error.value = reportError(failure.message); tab.value = 'catalog'; } }
}
async function remove(id) {
  const response = await deleteReportView(id);
  if (response.success) await loadViews();
  else error.value = reportError(response.message);
}
onMounted(async () => {
  try {
    const response = await fetchReportDatasets();
    if (!response.success) throw new Error(response.message);
    datasets.value = response.data.datasets || [];
    pending.value = response.data.pending || [];
    datasetsReady.value = true;
    if (route.query.tab === 'dashboard') tab.value = 'dashboard';
    else if (route.query.tab === 'analysis') tab.value = 'analysis';
    if (route.query.source_exception) await loadSource(route.query.source_exception);
  } catch (failure) {
    error.value = reportError(failure.message);
  } finally { loading.value = false; }
});
watch(() => JSON.stringify(route.query), async () => {
  if (!datasetsReady.value) return;
  error.value = ''; sourceNotice.value = '';
  if (route.query.source_exception) await loadSource(route.query.source_exception);
  else {
    sourceRequest++; activeSavedView.value = null; viewConfig.value = null; dashboardConfig.value = null;
    dashboardModule.value = dashboardModules.includes(route.query.module) ? route.query.module : '经营分析';
    tab.value = ['analysis', 'dashboard', 'saved'].includes(route.query.tab) ? route.query.tab : 'catalog';
    workbenchKey.value++;
  }
});
</script>
<style scoped>
.report-library {
  display: grid;
  gap: 16px;
}
h1 {
  margin: 0;
  font-size: 24px;
}
.catalog {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.catalog article {
  padding: 18px;
  background: #fff;
  border: 1px solid #dce3ec;
  border-radius: 6px;
}
.catalog h2 {
  font-size: 16px;
}
.catalog p,
header p {
  font-size: 13px;
  color: #526177;
  line-height: 1.7;
}
.report-library {
  min-width: 0;
}
.report-library :deep(.el-tabs) {
  min-width: 0;
  width: 100%;
}
.catalog article {
  min-width: 0;
}
.catalog p,
header p {
  overflow-wrap: anywhere;
}
@media (max-width: 600px) {
  .catalog {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<style scoped>
.library-hint { margin: 0 0 18px; color: #627086; font-size: 13px; }
.catalog article { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.catalog article h2, .catalog article p { margin: 0; }
.catalog article p { flex: 1; }
.catalog article :deep(.el-button) { margin-top: 8px; }
.pending-reports { margin-top: 22px; border: 1px solid #dce3ec; background: #fff; padding: 14px 18px; border-radius: 6px; }
.pending-reports summary { cursor: pointer; color: #526177; font-size: 14px; }
.pending-reports p, .saved-heading p { font-size: 12px; color: #627086; }
.saved-heading { display: flex; gap: 16px; align-items: center; justify-content: space-between; flex-wrap: wrap; margin-bottom: 16px; }
.history { grid-column: 1 / -1; width: 100%; margin-top: 8px; }
.history-note { color: #627086; font-size: 12px; line-height: 1.6; }
</style>
