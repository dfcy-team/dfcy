<template>
  <section class="rpa-page">
    <header class="rpa-header">
      <div>
        <h1 class="page-title">{{ title }}</h1>
        <p>{{ note }}</p>
      </div>
      <el-tag :type="connectionTag">{{ connectionState }}</el-tag>
    </header>

    <el-alert :title="boundaryNote" type="warning" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="connectionState === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-form v-if="filters.length" class="rpa-filter" inline @submit.prevent>
      <el-form-item v-for="filter in filters" :key="filter.key" :label="filter.label">
        <el-select v-if="filter.options" v-model="query[filter.key]" clearable placeholder="全部" style="width: 180px">
          <el-option v-for="option in filter.options" :key="option" :label="option" :value="option" />
        </el-select>
        <el-input v-else v-model="query[filter.key]" clearable placeholder="输入筛选条件" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="reloadFromStart">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border :empty-text="emptyText">
      <el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 130" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="column.type === 'status'" :type="statusType(row[column.prop])">{{ row[column.prop] || '-' }}</el-tag>
          <span v-else>{{ formatValue(row[column.prop]) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleActions.length" label="操作" fixed="right" :min-width="Math.max(150, visibleActions.length * 92)">
        <template #default="{ row }">
          <el-button
            v-for="action in visibleActions"
            :key="action.label"
            link
            :type="action.type || 'primary'"
            :disabled="rowActionAccess(action, row).disabled"
            :title="rowActionAccess(action, row).reason"
            :loading="actionLoading === `${action.label}:${row.id}`"
            @click="runAction(action, row)"
          >
            {{ action.label }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      layout="total, sizes, prev, pager, next"
      :total="total"
      :page-sizes="[10, 20, 50]"
      @current-change="loadData"
      @size-change="reloadFromStart"
    />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { getActionAccess } from '../utils/actionAccess';

const props = defineProps({
  title: { type: String, required: true },
  note: { type: String, required: true },
  boundaryNote: {
    type: String,
    default: '仅管理 Mock/dry-run 任务，不调用 Agent 执行接口，不连接真实平台。'
  },
  loader: { type: Function, required: true },
  columns: { type: Array, default: () => [] },
  filters: { type: Array, default: () => [] },
  rowActions: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无数据' }
});

const auth = useAuthStore();
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const actionLoading = ref('');
const connectionState = ref('loading');
const message = ref('');
const query = reactive(Object.fromEntries(props.filters.map((filter) => [filter.key, ''])));
const visibleActions = computed(() => props.rowActions.filter((action) => getActionAccess(auth, action).visible));
const connectionTag = computed(() => ({ connected: 'success', degraded: 'warning', fallback: 'warning', error: 'danger' }[connectionState.value] || 'info'));

function rowActionAccess(action, row) {
  const stateDisabled = typeof action.disabled === 'function' ? action.disabled(row) : action.disabled;
  return getActionAccess(auth, { ...action, disabled: stateDisabled });
}

function statusType(value) {
  return {
    success: 'success', online: 'success', active: 'success', stable: 'success', held: 'warning',
    running: 'primary', claimed: 'primary', retrying: 'warning', manual_required: 'warning',
    failed: 'danger', changed: 'danger', disabled: 'info', offline: 'info', cancelled: 'info',
    production_disabled: 'danger', mock: 'info', dry_run: 'warning'
  }[value] || 'info';
}

function formatValue(value) {
  if (value === true) return '是';
  if (value === false) return '否';
  if (Array.isArray(value)) return value.join(', ');
  return value ?? '-';
}

async function loadData() {
  loading.value = true;
  message.value = '';
  try {
    const params = { page: page.value, page_size: pageSize.value };
    for (const [key, value] of Object.entries(query)) if (value) params[key] = value;
    const response = await props.loader(params);
    if (!response.success) throw Object.assign(new Error(response.message || '请求失败'), { response });
    const data = response.data || {};
    rows.value = Array.isArray(data.results) ? data.results : Array.isArray(data.items) ? data.items : [];
    total.value = Number(data.count ?? rows.value.length);
    connectionState.value = data.api_status || data.connection_status || data.status || 'mock';
    if (connectionState.value === 'fallback') connectionState.value = 'degraded';
  } catch (error) {
    connectionState.value = 'error';
    message.value = error?.response?.message || error?.message || '请求失败';
    rows.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

function reloadFromStart() {
  page.value = 1;
  loadData();
}

function resetFilters() {
  Object.keys(query).forEach((key) => { query[key] = ''; });
  reloadFromStart();
}

async function runAction(action, row) {
  const access = rowActionAccess(action, row);
  if (!access.allowed) return ElMessage.warning(access.reason);
  try {
    if (action.confirmMessage) {
      await ElMessageBox.confirm(
        typeof action.confirmMessage === 'function' ? action.confirmMessage(row) : action.confirmMessage,
        action.confirmTitle || '确认操作',
        { type: action.confirmType || 'warning' }
      );
    }
    actionLoading.value = `${action.label}:${row.id}`;
    const response = await action.handler(row);
    if (!response?.success) throw new Error(response?.message || '操作失败');
    ElMessage.success(response.message || '操作完成');
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
.rpa-page { display: grid; gap: 16px; }
.rpa-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.rpa-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.rpa-filter { padding: 12px; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
</style>
