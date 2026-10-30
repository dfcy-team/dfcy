<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { canAccessPath } from '../../router/menu';
import { fetchStoreAuthorizations, fetchWarehouseAuthorizations, fetchStoreAuthorizationDetail, fetchWarehouseAuthorizationDetail, fetchConnectionCapabilities, fetchAuthorizationSubjectCandidates } from '../../api/integrations';
import { authorizationPermission, authorizationQuery, authorizationSummary } from '../../utils/authorizationCenter';
import IntegrationPlatformPicker from '../../components/IntegrationPlatformPicker.vue';
const SubjectApiAccessDialog = defineAsyncComponent(() => import('../../components/SubjectApiAccessDialog.vue'));

type Kind = 'store' | 'warehouse';
type Summary = ReturnType<typeof authorizationSummary>;
type Capability = { capability_code: string; read_enabled: boolean; write_enabled: boolean; status: string };
const auth = useAuthStore(), router = useRouter();
const kinds = computed(() => (['store', 'warehouse'] as Kind[]).filter(value => auth.hasPermission(authorizationPermission(value))));
const kind = ref<Kind>('store'), platform = ref(''), status = ref(''), page = ref(1);
const rows = ref<Summary[]>([]), total = ref(0), loading = ref(false), error = ref('');
const detail = ref<Summary | null>(null), detailOpen = ref(false), detailLoading = ref(false), detailError = ref('');
const capabilities = ref<Capability[]>([]), capabilityError = ref('');
type Subject = { id: number; name: string; code?: string; external_warehouse_code?: string; api_access_available?: boolean };
const maintenanceOpen = ref(false), maintenanceKind = ref<Kind>('store'), maintenanceRow = ref<Subject | null>(null);
const pickerOpen = ref(false), subjectRows = ref<Subject[]>([]), subjectSearch = ref(''), subjectPage = ref(1), subjectTotal = ref(0), subjectLoading = ref(false), subjectError = ref('');
let subjectSequence = 0;
const canMaintain = computed(() => auth.hasPermission('integrations.view') && auth.hasPermission(authorizationPermission(kind.value)));
const canCreate = computed(() => canMaintain.value && auth.hasPermission(kind.value === 'store' ? 'integrations.store.authorize' : 'integrations.warehouse.authorize'));
let listSequence = 0, detailSequence = 0;
const labels: Record<string, string> = { active: '已授权', expired: '已过期', revoked: '已撤销', pending: '待授权', error: '异常', failed: '失败', unknown: '状态未知' };
const platforms = computed(() => kind.value === 'store' ? ['shopee', 'lazada', 'tiktok'] : ['jifeng_wms']);
function time(value: string) { return value ? `${value.replace('T', ' ')}` : '未提供'; }
async function load() {
  const seq = ++listSequence;
  rows.value = []; total.value = 0; error.value = '';
  if (!kinds.value.includes(kind.value)) { loading.value = false; return; }
  loading.value = true;
  const requestedKind = kind.value;
  try {
    const response = await (requestedKind === 'store' ? fetchStoreAuthorizations : fetchWarehouseAuthorizations)(authorizationQuery(requestedKind, platform.value, status.value, page.value));
    if (seq !== listSequence) return;
    if (!response?.success) throw new Error(response?.message || '授权列表加载失败');
    rows.value = (response.data?.results || []).map(row => authorizationSummary(row, requestedKind));
    total.value = Number(response.data?.count || 0);
  } catch (cause) { if (seq === listSequence) error.value = cause instanceof Error ? cause.message : '授权列表加载失败'; }
  finally { if (seq === listSequence) loading.value = false; }
}
function search() { page.value = 1; load(); }
function closeDetail() { ++detailSequence; detail.value = null; capabilities.value = []; detailLoading.value = false; }
async function openDetail(row: Summary) {
  const seq = ++detailSequence, requestedKind = kind.value;
  detail.value = null; capabilities.value = []; detailError.value = ''; capabilityError.value = ''; detailOpen.value = true; detailLoading.value = true;
  try {
    const response = await (requestedKind === 'store' ? fetchStoreAuthorizationDetail : fetchWarehouseAuthorizationDetail)(row.id);
    if (seq !== detailSequence) return;
    if (!response?.success) throw new Error(response?.message || '详情加载失败');
    detail.value = authorizationSummary(response.data, requestedKind);
    if (requestedKind === 'store') {
      try {
        const result = await fetchConnectionCapabilities(row.id);
        if (seq !== detailSequence) return;
        if (!result?.success) throw new Error(result?.message || '能力加载失败');
        capabilities.value = result.data?.results || [];
      } catch (cause) { if (seq === detailSequence) capabilityError.value = cause instanceof Error ? cause.message : '能力加载失败'; }
    }
  } catch (cause) { if (seq === detailSequence) detailError.value = cause instanceof Error ? cause.message : '详情加载失败'; }
  finally { if (seq === detailSequence) detailLoading.value = false; }
}
const archivePath = computed(() => kind.value === 'store' ? '/master-data/stores' : '/master-data/warehouses');
function maintain(row: Subject) {
  if (!canMaintain.value || !row?.id) return;
  maintenanceKind.value = kind.value; maintenanceRow.value = { ...row }; maintenanceOpen.value = true;
}
function maintainDetail() {
  if (!detail.value) return;
  maintain({ id: detail.value.subjectId, name: detail.value.name, code: detail.value.code, external_warehouse_code: kind.value === 'warehouse' ? detail.value.externalId : undefined });
}
async function loadSubjects() {
  const seq = ++subjectSequence; subjectRows.value = []; subjectTotal.value = 0; subjectError.value = '';
  if (!canCreate.value) return;
  subjectLoading.value = true;
  try {
    const response = await fetchAuthorizationSubjectCandidates({ type: kind.value, page: subjectPage.value, page_size: 20, search: subjectSearch.value });
    if (seq !== subjectSequence) return;
    if (!response?.success) throw new Error(response?.message || '档案加载失败');
    subjectRows.value = response.data?.results || []; subjectTotal.value = Number(response.data?.count || 0);
  } catch (cause) { if (seq === subjectSequence) subjectError.value = cause instanceof Error ? cause.message : '档案加载失败'; }
  finally { if (seq === subjectSequence) subjectLoading.value = false; }
}
function openCreate() { if (!canCreate.value) return; subjectSearch.value = ''; subjectPage.value = 1; pickerOpen.value = true; loadSubjects(); }
function chooseSubject(row: Subject) { if (!canCreate.value || (kind.value === 'warehouse' && !row.api_access_available)) return; pickerOpen.value = false; maintain(row); }
function changed() { load(); if (detail.value && detailOpen.value) openDetail(detail.value); }
function openSync(path: string) {
  if (!detail.value || !canAccessPath(auth.currentUser, path)) return;
  router.push({ path, query: { subject_key: `${kind.value}:${detail.value.subjectId}` } });
}
function openArchive() {
  if (!canAccessPath(auth.currentUser, archivePath.value)) return;
  router.push(kind.value === 'store' && detail.value ? { path: archivePath.value, query: { store_id: String(detail.value.subjectId), panel: 'api' } } : archivePath.value);
}
watch([kind, kinds], () => {
  ++subjectSequence; pickerOpen.value = false; maintenanceOpen.value = false; maintenanceRow.value = null;
  ++detailSequence; detailOpen.value = false; detail.value = null;
  if (!kinds.value.includes(kind.value) && kinds.value.length) kind.value = kinds.value[0];
  platform.value = ''; status.value = ''; page.value = 1; load();
}, { immediate: true });
watch(canMaintain, allowed => { if (!allowed) { maintenanceOpen.value = false; maintenanceRow.value = null; } });
watch(canCreate, allowed => { if (!allowed) { ++subjectSequence; pickerOpen.value = false; subjectRows.value = []; subjectLoading.value = false; } });
onBeforeUnmount(() => { ++listSequence; ++detailSequence; ++subjectSequence; });
</script>

<template>
  <section class="authorization-center">
    <header><div><p>API 数据接入 / 授权接入</p><h1>店铺与仓库授权</h1><p>按平台查看授权连接、绑定对象和读取能力。</p></div><el-tag v-if="useMock" type="warning">模拟数据</el-tag><el-button v-if="canCreate" type="primary" @click="openCreate">新增授权</el-button><el-button :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="!kinds.length" title="当前账号没有授权查看权限" type="warning" :closable="false" />
    <template v-else>
      <nav aria-label="授权类型"><button v-for="value in kinds" :key="value" type="button" :aria-pressed="kind === value" @click="kind = value">{{ value === 'store' ? '店铺授权' : '仓库授权' }}</button></nav>
      <div class="filters"><IntegrationPlatformPicker v-model="platform" :options="platforms" @change="search" /><el-select v-model="status" aria-label="授权状态筛选" placeholder="全部授权状态" clearable @change="search"><el-option v-for="value in ['pending','active','expired','revoked','error']" :key="value" :value="value" :label="labels[value]" /></el-select></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table v-else v-loading="loading" :data="rows" row-key="id" border empty-text="当前条件下没有授权记录">
        <el-table-column prop="name" label="绑定对象" min-width="180" /><el-table-column prop="platform" label="平台／服务商" min-width="130" /><el-table-column prop="region" label="站点／国家" width="120" />
        <el-table-column label="授权状态" width="110"><template #default="{row}">{{ labels[row.status] || row.status }}</template></el-table-column>
        <el-table-column label="有效期（接口原时区）" min-width="220"><template #default="{row}">{{ time(row.expiresAt) }}</template></el-table-column>
        <el-table-column prop="externalId" label="外部店铺／仓库编号" min-width="190" />
        <el-table-column label="操作" width="120" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openDetail(row)">查看详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="!error" v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </template>
    <el-drawer v-model="detailOpen" title="授权详情" size="min(720px, 96vw)" @closed="closeDetail">
      <div v-loading="detailLoading"><el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <template v-if="detail"><h2>{{ detail.name }}</h2><dl><dt>授权编号</dt><dd>{{ detail.id }}</dd><dt>绑定档案</dt><dd>{{ detail.code }}（ID {{ detail.subjectId }}）</dd><dt>接入配置 ID</dt><dd>{{ detail.configId }}</dd><dt>外部编号</dt><dd>{{ detail.externalId }}</dd><dt>授权状态</dt><dd>{{ labels[detail.status] || detail.status }}</dd><dt>有效期</dt><dd>{{ time(detail.expiresAt) }}</dd><dt>最近错误代码</dt><dd>{{ detail.lastError || '未记录' }}</dd></dl>
          <h3>{{ kind === 'store' ? '连接能力' : '仓库读取配置' }}</h3>
          <el-alert v-if="capabilityError" :title="capabilityError" type="error" :closable="false" />
          <el-table v-else-if="kind === 'store'" :data="capabilities" empty-text="接口未返回能力配置"><el-table-column prop="capability_code" label="能力" /><el-table-column label="读取开关"><template #default="{row}">{{ row.read_enabled === true ? '开启' : '关闭' }}</template></el-table-column><el-table-column prop="status" label="配置状态" /></el-table>
          <p v-else>读取开关：{{ detail.readEnabled === true ? '开启' : detail.readEnabled === false ? '关闭' : '接口未提供' }}</p><p class="note">授权状态与读取开关不代表同步成功，运行结果请在同步管理中核对。</p>
          <el-button v-if="canAccessPath(auth.currentUser, archivePath)" @click="openArchive">{{ kind === 'store' ? '前往店铺授权维护' : '前往仓库档案维护' }}</el-button>
          <el-button v-if="canMaintain" type="primary" @click="maintainDetail">管理主体授权</el-button>
          <p class="note">管理入口按当前店铺／仓库汇总全部授权；请在维护窗口核对目标连接。下方同步入口展示该主体的全部任务与运行。</p>
          <el-button v-if="canAccessPath(auth.currentUser, '/integrations/sync-jobs')" @click="openSync('/integrations/sync-jobs')">查看主体任务</el-button>
          <el-button v-if="canAccessPath(auth.currentUser, '/integrations/sync-runs')" @click="openSync('/integrations/sync-runs')">查看主体运行记录</el-button>
        </template>
      </div>
    </el-drawer>
    <el-dialog v-model="pickerOpen" title="选择授权主体" width="min(720px, 94vw)" @closed="subjectSequence++; subjectRows = []">
      <p>选择已有{{ kind === 'store' ? '店铺' : '仓库' }}档案，再配置授权连接。已有授权也可从这里维护。</p>
      <el-input v-model="subjectSearch" aria-label="搜索授权主体" placeholder="输入名称或编码" clearable @keyup.enter="subjectPage = 1; loadSubjects()" /><el-button @click="subjectPage = 1; loadSubjects()">查询主体</el-button>
      <el-alert v-if="subjectError" :title="subjectError" type="error" :closable="false" />
      <el-table v-else v-loading="subjectLoading" :data="subjectRows" empty-text="没有可选择的档案"><el-table-column prop="name" label="名称" /><el-table-column prop="code" label="编码" /><el-table-column label="操作" width="150"><template #default="{row}"><el-button link type="primary" :disabled="kind === 'warehouse' && !row.api_access_available" :title="kind === 'warehouse' && !row.api_access_available ? '该仓库尚未开放 API 接入' : ''" @click="chooseSubject(row)">选择并配置</el-button></template></el-table-column></el-table>
      <el-pagination v-model:current-page="subjectPage" :total="subjectTotal" :page-size="20" layout="total, prev, pager, next" @current-change="loadSubjects" />
    </el-dialog>
    <SubjectApiAccessDialog v-if="maintenanceRow" v-model="maintenanceOpen" :subject-type="maintenanceKind" :row="maintenanceRow" @changed="changed" />
  </section>
</template>

<style scoped>
.authorization-center { background:#fff; color:#24324b; padding:8px; } header { display:flex; align-items:center; gap:16px; } header div { flex:1; } h1 { font-size:26px; margin:8px 0; } p,.note { color:#64748b; } nav { display:flex; gap:8px; margin:24px 0; } nav button { border:1px solid #dce2ea; border-radius:6px; background:#fff; padding:12px 24px; cursor:pointer; } nav button[aria-pressed="true"] { background:#eff6ff; color:#1d4ed8; border-color:#2563eb; } .filters { display:grid; gap:16px; margin-bottom:20px; } .filters .el-select { max-width:240px; } .el-pagination { margin-top:20px; } dl { display:grid; grid-template-columns:130px 1fr; gap:12px; } dd { margin:0; overflow-wrap:anywhere; } @media(max-width:600px) { header { flex-wrap:wrap; } header div { flex-basis:100%; } dl { grid-template-columns:100px 1fr; } }
</style>
