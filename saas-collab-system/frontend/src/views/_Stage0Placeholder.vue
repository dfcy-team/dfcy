<template>
  <section class="stage0-page">
    <header class="stage0-header">
      <div>
        <h1 class="page-title">{{ title }}</h1>
        <p class="stage0-note">阶段1联调占位：Mock 模式展示本地数据，关闭 Mock 后尝试调用阶段1 API；不执行真实业务提交。</p>
      </div>
      <div class="stage0-tags">
        <el-tag type="info">API: {{ apiPath }}</el-tag>
        <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
      </div>
    </header>

    <el-form class="stage0-search" inline>
      <el-form-item v-for="item in searchFields" :key="item" :label="item">
        <el-input placeholder="Mock 搜索条件" disabled />
      </el-form-item>
      <el-form-item>
        <el-button disabled>搜索占位</el-button>
        <el-button disabled>重置占位</el-button>
      </el-form-item>
    </el-form>

    <div class="stage0-actions">
      <el-button v-for="action in actions" :key="action" disabled>{{ action }}</el-button>
    </div>

    <div class="placeholder-grid">
      <div v-for="field in fields" :key="field" class="placeholder-card">
        <span class="field-label">{{ field }}</span>
        <span class="field-value">{{ sampleValue(field) }}</span>
      </div>
    </div>

    <el-card v-if="apiLoader" class="stage0-api-card" shadow="never">
      <template #header>
        <strong>API / Mock 返回预览</strong>
      </template>
      <pre>{{ responsePreview }}</pre>
    </el-card>

    <div v-if="extraItems.length" class="stage0-extra">
      <span v-for="item in extraItems" :key="item">{{ item }}</span>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

const props = defineProps({
  title: { type: String, required: true },
  apiPath: { type: String, default: 'pending' },
  fields: { type: Array, default: () => [] },
  searchFields: { type: Array, default: () => ['编号', '状态'] },
  actions: { type: Array, default: () => ['新增占位', '导出占位'] },
  extraItems: { type: Array, default: () => [] },
  apiLoader: { type: Function, default: null }
});

const { title, apiPath, fields, searchFields, actions, extraItems, apiLoader } = props;
const apiResponse = ref(null);
const dataStatus = ref(apiLoader ? 'loading' : 'mock');

const responseData = computed(() => apiResponse.value?.data || {});
const responseItems = computed(() => {
  const data = responseData.value;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.items)) return data.items;
  return data && Object.keys(data).length ? [data] : [];
});
const firstItem = computed(() => responseItems.value[0] || {});
const responsePreview = computed(() => JSON.stringify(apiResponse.value || {}, null, 2));
const statusTagType = computed(() => {
  if (dataStatus.value === 'api') return 'success';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'error') return 'danger';
  return 'info';
});

function sampleValue(field) {
  const normalizedField = String(field).toLowerCase();
  const matchKey = Object.keys(firstItem.value).find((key) => normalizedField.includes(key.toLowerCase()));
  if (matchKey) return firstItem.value[matchKey] ?? 'Mock 字段占位';
  return responseItems.value.length ? '接口字段待映射' : 'Mock 字段占位';
}

onMounted(async () => {
  if (!apiLoader) return;
  try {
    apiResponse.value = await apiLoader();
    dataStatus.value = apiResponse.value?.data?.api_status || apiResponse.value?.data?.status || 'api';
  } catch (error) {
    dataStatus.value = 'error';
    apiResponse.value = {
      success: false,
      code: 'FRONTEND_API_ERROR',
      message: error?.message || 'request failed',
      data: {}
    };
  }
});
</script>

<style scoped>
.stage0-page {
  display: grid;
  gap: 16px;
}

.stage0-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.stage0-note {
  margin: -8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.stage0-search {
  padding: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}

.stage0-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stage0-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stage0-extra span {
  padding: 5px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  font-size: 12px;
}

.stage0-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.stage0-api-card {
  border-radius: 8px;
}

.stage0-api-card pre {
  max-height: 240px;
  margin: 0;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
}
</style>
