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

    <el-form v-if="filters.length" class="phase2-filter" inline>
      <el-form-item v-for="filter in filters" :key="filter" :label="filter">
        <el-input placeholder="筛选占位" disabled />
      </el-form-item>
      <el-form-item>
        <el-button disabled>筛选</el-button>
        <el-button disabled>重置</el-button>
      </el-form-item>
    </el-form>

    <div v-if="actions.length || actionConfigs.length" class="phase2-actions">
      <el-button v-for="action in actions" :key="action" disabled>{{ action }}</el-button>
      <el-button
        v-for="action in actionConfigs"
        :key="action.label"
        :type="action.type || 'default'"
        :disabled="action.disabled"
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
    </el-table>

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
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';

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
const detail = ref({});
const loading = ref(false);
const actionLoading = ref('');
const dataStatus = ref('loading');
const message = ref('');

const tagType = computed(() => {
  if (dataStatus.value === 'error') return 'danger';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'connected') return 'success';
  return 'info';
});
const isEmpty = computed(() => (props.mode === 'list' ? rows.value.length === 0 : Object.keys(detail.value).length === 0));

function getRows(data) {
  if (Array.isArray(data)) return data;
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
  try {
    const response = await props.loader();
    if (!response.success) throw new Error(response.message || '接口返回失败');
    rows.value = getRows(response.data);
    detail.value = getDetail(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'mock';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    dataStatus.value = 'error';
    message.value = error?.message || '请求失败';
  } finally {
    loading.value = false;
  }
}

async function runAction(action) {
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
pre { max-height: 260px; margin: 0; overflow: auto; font-size: 12px; line-height: 1.5; }
</style>
