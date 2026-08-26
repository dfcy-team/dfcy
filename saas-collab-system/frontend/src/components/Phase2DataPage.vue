<template>
  <section class="phase2-page">
    <header class="phase2-header">
      <div>
        <h1 class="page-title">{{ title }}</h1>
        <p>{{ note }}</p>
      </div>
      <el-tag :type="tagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert v-if="riskNote" :title="riskNote" type="warning" show-icon :closable="false" />

    <el-form v-if="filterDefinitions.length" class="phase2-filter" inline @submit.prevent>
      <el-form-item v-for="filter in filterDefinitions" :key="filter.key" :label="filter.label">
        <el-select v-if="filter.type === 'select'" v-model="query[filter.key]" clearable placeholder="全部">
          <el-option v-for="option in filter.options || []" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <el-input v-else v-model="query[filter.key]" clearable :placeholder="`筛选${filter.label}`" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="loadData">刷新</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <div v-if="actions.length || visibleActionConfigs.length" class="phase2-actions">
      <el-button v-for="action in actions" :key="action" disabled>{{ action }}</el-button>
      <el-button
        v-for="action in visibleActionConfigs"
        :key="action.label"
        :type="action.type || 'default'"
        :disabled="actionAccess(action).disabled"
        :title="actionAccess(action).reason"
        :loading="actionLoading === action.label"
        @click="runAction(action)"
      >
        {{ action.label }}
      </el-button>
    </div>

    <el-alert v-if="message" :title="message" :type="dataStatus === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <section v-if="mode === 'list'" class="phase2-table-shell">
      <div class="phase2-summary"><span>当前结果</span><strong>{{ filteredRows.length }}</strong><small>数据范围：当前租户及角色授权范围</small></div>
      <el-table v-loading="loading" :data="filteredRows" border :empty-text="emptyText" @row-click="openRowDetail">
      <el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 130" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="column.type === 'status'" :type="statusType(row[column.prop])">{{ row[column.prop] || '-' }}</el-tag>
          <span v-else>{{ formatValue(row[column.prop]) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="92" fixed="right"><template #default="{ row }"><el-button link type="primary" @click.stop="openRowDetail(row)">查看</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-card v-else v-loading="loading" shadow="never">
      <template #header>详情</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item v-for="field in detailFields" :key="field.prop" :label="field.label">
          <pre v-if="field.type === 'json'">{{ formatJson(detail[field.prop]) }}</pre>
          <el-tag v-else-if="field.type === 'status'" :type="statusType(detail[field.prop])">{{ detail[field.prop] || '-' }}</el-tag>
          <span v-else>{{ formatValue(detail[field.prop]) }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-empty v-if="!loading && !message && isEmpty" :description="emptyText" />

    <el-drawer v-model="drawerOpen" title="数据接入详情" size="min(520px, 92vw)">
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="column in columns" :key="column.prop" :label="column.label">
          {{ formatValue(selectedRow[column.prop]) }}
        </el-descriptions-item>
      </el-descriptions>
      <el-alert class="drawer-alert" title="仅展示当前租户的脱敏配置、同步状态与计数，不展示明文凭据。" type="info" :closable="false" />
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { getActionAccess } from '../utils/actionAccess';

const props = defineProps({
  title: { type: String, required: true },
  note: { type: String, default: '' },
  riskNote: { type: String, default: '' },
  mode: { type: String, default: 'list' },
  loader: { type: Function, required: true },
  columns: { type: Array, default: () => [] },
  detailFields: { type: Array, default: () => [] },
  filters: { type: Array, default: () => [] },
  actions: { type: Array, default: () => [] },
  actionConfigs: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无数据' }
});

const rows = ref([]);
const auth = useAuthStore();
const detail = ref({});
const loading = ref(false);
const actionLoading = ref('');
const dataStatus = ref('loading');
const message = ref('');
const query = reactive({});
const drawerOpen = ref(false);
const selectedRow = ref({});
const filterDefinitions = computed(() => props.filters.map((filter) => {
  if (typeof filter === 'object') return filter;
  const column = props.columns.find((item) => item.label === filter);
  return { key: column?.prop || filter, label: filter, type: 'text' };
}));
const filteredRows = computed(() => rows.value.filter((row) => filterDefinitions.value.every((filter) => {
  const expected = query[filter.key];
  if (expected === '' || expected === null || expected === undefined) return true;
  const actual = row[filter.key];
  return filter.type === 'select'
    ? String(actual ?? '') === String(expected)
    : String(actual ?? '').toLowerCase().includes(String(expected).toLowerCase());
})));

const tagType = computed(() => {
  if (dataStatus.value === 'error') return 'danger';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'connected') return 'success';
  return 'info';
});
const isEmpty = computed(() => (props.mode === 'list' ? rows.value.length === 0 : Object.keys(detail.value).length === 0));
const actionAccess = (action) => getActionAccess(auth, action);
const visibleActionConfigs = computed(() => props.actionConfigs.filter((action) => actionAccess(action).visible));

function getRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

function getDetail(data) {
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

function formatValue(value) {
  if (Array.isArray(value)) return value.join(', ');
  if (value === true) return '是';
  if (value === false) return '否';
  return value ?? '-';
}

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2);
}

function statusType(value) {
  return {
    success: 'success',
    completed: 'success',
    active: 'success',
    enabled: 'success',
    failed: 'danger',
    exception: 'danger',
    rejected: 'danger',
    disabled: 'info',
    pending: 'warning',
    retrying: 'warning',
    manual_required: 'warning',
    security_review_required: 'warning',
    production_disabled: 'danger'
  }[value] || 'info';
}

function resetFilters() {
  filterDefinitions.value.forEach((filter) => { query[filter.key] = ''; });
  loadData();
}

function openRowDetail(row) {
  selectedRow.value = row;
  drawerOpen.value = true;
}

async function loadData() {
  loading.value = true;
  try {
    const response = await props.loader();
    if (!response.success) throw new Error(response.message || '接口返回失败');
    rows.value = getRows(response.data);
    detail.value = getDetail(response.data);
    // A successful response without an explicit capability/status is not
    // evidence of a live connection. Keep the page pending until the API
    // supplies an authoritative status.
    dataStatus.value = response.data?.api_status
      || response.data?.status
      || response.api_status
      || response.status
      || 'pending';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    dataStatus.value = 'error';
    message.value = error?.message || '请求失败';
  } finally {
    loading.value = false;
  }
}

async function runAction(action) {
  const access = actionAccess(action);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  if (typeof action.handler !== 'function') return;
  try {
    if (action.confirmMessage) {
      await ElMessageBox.confirm(action.confirmMessage, action.confirmTitle || '确认操作', {
        type: action.confirmType || 'warning'
      });
    }
    actionLoading.value = action.label;
    const response = await action.handler({ rows: rows.value, detail: detail.value });
    if (!response?.success) throw new Error(response?.message || '操作失败');
    ElMessage.success(response.message || '操作已提交');
    await loadData();
  } catch (error) {
    if (error === 'cancel') return;
    ElMessage.error(error?.message || '操作失败');
  } finally {
    actionLoading.value = '';
  }
}

onMounted(loadData);
</script>

<style scoped>
.phase2-page { display: grid; gap: 16px; }
.phase2-header { display: flex; justify-content: space-between; gap: 16px; }
.phase2-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.phase2-filter { padding: 12px; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.phase2-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.phase2-table-shell { overflow: hidden; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.phase2-summary { display: flex; align-items: baseline; gap: 12px; padding: 13px 16px; border-bottom: 1px solid #e5eaf0; }
.phase2-summary span, .phase2-summary small { color: #64748b; font-size: 12px; }.phase2-summary strong { color: #172033; font-size: 20px; }.phase2-summary small { margin-left: auto; }
.drawer-alert { margin-top: 16px; }
pre { max-height: 260px; margin: 0; overflow: auto; font-size: 12px; line-height: 1.5; }
</style>
