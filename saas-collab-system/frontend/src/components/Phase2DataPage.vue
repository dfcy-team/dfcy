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

    <el-form v-if="filterConfigs.length" class="phase2-filter" inline @submit.prevent="applyFilters">
      <el-form-item v-for="filter in filterConfigs" :key="filter.key" :label="filter.label">
        <el-select v-if="filter.options" v-model="query[filter.key]" clearable placeholder="全部">
          <el-option v-for="option in filter.options" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <el-input v-else v-model="query[filter.key]" clearable :placeholder="filter.placeholder || '请输入'" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading">筛选</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <el-form v-else-if="filters.length" class="phase2-filter" inline>
      <el-form-item v-for="filter in filters" :key="filter" :label="filter">
        <el-input placeholder="筛选占位" disabled />
      </el-form-item>
      <el-form-item>
        <el-button disabled>筛选</el-button>
        <el-button disabled>重置</el-button>
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

    <el-table v-if="mode === 'list'" v-loading="loading" :data="rows" border :empty-text="emptyText">
      <el-table-column v-for="column in columns" :key="column.prop" :prop="column.prop" :label="column.label" :min-width="column.width || 130" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="column.type === 'status'" :type="statusType(row[column.prop])">{{ row[column.prop] || '-' }}</el-tag>
          <span v-else>{{ formatValue(row[column.prop]) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleRowActionConfigs.length" label="操作" :min-width="Math.max(130, visibleRowActionConfigs.length * 110)" fixed="right">
        <template #default="{ row }">
          <el-button
            v-for="action in visibleRowActionConfigs"
            :key="action.label"
            link
            :type="action.type || 'primary'"
            :disabled="actionAccess(action).disabled"
            :title="actionAccess(action).reason"
            @click="runAction(action, row)"
          >
            {{ action.label }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="mode === 'list' && total > 0"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @current-change="loadData"
      @size-change="changePageSize"
    />

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
  filterConfigs: { type: Array, default: () => [] },
  actions: { type: Array, default: () => [] },
  actionConfigs: { type: Array, default: () => [] },
  rowActionConfigs: { type: Array, default: () => [] },
  emptyText: { type: String, default: '暂无数据' }
});

const rows = ref([]);
const query = reactive({});
const auth = useAuthStore();
const detail = ref({});
const loading = ref(false);
const actionLoading = ref('');
const dataStatus = ref('loading');
const message = ref('');
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);

const tagType = computed(() => {
  if (dataStatus.value === 'error') return 'danger';
  if (['fallback', 'degraded'].includes(dataStatus.value)) return 'warning';
  if (dataStatus.value === 'connected') return 'success';
  return 'info';
});
const isEmpty = computed(() => (props.mode === 'list' ? rows.value.length === 0 : Object.keys(detail.value).length === 0));
const actionAccess = (action) => getActionAccess(auth, action);
const visibleActionConfigs = computed(() => props.actionConfigs.filter((action) => actionAccess(action).visible));
const visibleRowActionConfigs = computed(() => props.rowActionConfigs.filter((action) => actionAccess(action).visible));

function initializeFilters() {
  props.filterConfigs.forEach((filter) => { query[filter.key] = ''; });
}

function applyFilters() {
  page.value = 1;
  loadData();
}

function resetFilters() {
  initializeFilters();
  applyFilters();
}

function changePageSize() {
  page.value = 1;
  loadData();
}

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

async function loadData() {
  loading.value = true;
  message.value = '';
  try {
    const response = await props.loader({
      ...query,
      page: page.value,
      page_size: pageSize.value
    });
    if (!response.success) throw new Error(response.message || '接口返回失败');
    rows.value = getRows(response.data);
    detail.value = getDetail(response.data);
    total.value = Number(response.data?.count ?? rows.value.length);
    dataStatus.value = response.data?.api_status || response.data?.status || 'mock';
    if (['fallback', 'degraded'].includes(response.data?.api_status)) message.value = response.message;
  } catch (error) {
    dataStatus.value = 'error';
    message.value = error?.message || '请求失败';
  } finally {
    loading.value = false;
  }
}

async function runAction(action, row = null) {
  const access = actionAccess(action);
  if (!access.allowed) {
    ElMessage.warning(access.reason);
    return;
  }
  if (typeof action.handler !== 'function') return;
  if (dataStatus.value !== 'connected' && action.allowMock !== true) {
    ElMessage.info('当前不是已验证的后端联调数据，操作保持 pending，不发送业务写入请求。');
    return;
  }
  try {
    if (action.confirmMessage) {
      await ElMessageBox.confirm(action.confirmMessage, action.confirmTitle || '确认操作', {
        type: action.confirmType || 'warning'
      });
    }
    actionLoading.value = action.label;
    const response = await action.handler({ row, rows: rows.value, detail: detail.value });
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

initializeFilters();
onMounted(loadData);
</script>

<style scoped>
.phase2-page { display: grid; gap: 16px; }
.phase2-header { display: flex; justify-content: space-between; gap: 16px; }
.phase2-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.phase2-filter { padding: 12px; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.phase2-actions { display: flex; flex-wrap: wrap; gap: 8px; }
pre { max-height: 260px; margin: 0; overflow: auto; font-size: 12px; line-height: 1.5; }
</style>
