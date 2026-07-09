<template>
  <section class="rpa-page">
    <header class="rpa-header">
      <div>
        <h1 class="page-title">RPA任务详情</h1>
        <p class="page-note">后续对接API路径：GET /api/internal/rpa/tasks/{id}/；不调用 Agent 执行接口 /api/rpa/*。</p>
      </div>
      <el-tag :type="statusTagType">{{ dataStatus }}</el-tag>
    </header>

    <el-alert title="管理后台仅查看RPA任务和占位操作，不执行真实RPA，不连接真实BigSeller，不保存真实截图或页面快照。" type="info" show-icon :closable="false" />
    <el-alert v-if="warningMessage" :title="warningMessage" type="warning" show-icon :closable="false" />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>任务基础信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务编号">{{ detail.task_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="任务类型">{{ detail.task_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="业务类型">{{ detail.business_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="业务ID">{{ detail.business_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Agent">{{ detail.agent || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="rpaStatusType(detail.status)">{{ detail.status || '-' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="重试次数">{{ detail.retry_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="人工接管">{{ detail.manual_required ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="错误原因">{{ detail.error_message || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>payload JSON展示</template>
      <pre class="json-block">{{ formatJson(detail.payload) }}</pre>
    </el-card>

    <el-card shadow="never">
      <template #header>result JSON展示</template>
      <pre class="json-block">{{ formatJson(detail.result) }}</pre>
    </el-card>

    <el-card shadow="never">
      <template #header>步骤日志</template>
      <el-table :data="logs" border empty-text="暂无步骤日志">
        <el-table-column prop="occurred_at" label="时间" min-width="170" />
        <el-table-column prop="level" label="级别" min-width="90" />
        <el-table-column prop="step_name" label="步骤" min-width="150" />
        <el-table-column prop="message" label="消息" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>截图列表</template>
      <el-table :data="screenshots" border empty-text="暂无截图占位">
        <el-table-column prop="step_name" label="节点" min-width="150" />
        <el-table-column prop="screenshot_url" label="demo URL / 占位引用" min-width="260" show-overflow-tooltip />
        <el-table-column prop="message" label="说明" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <div class="rpa-actions">
      <el-button disabled>重试按钮占位</el-button>
      <el-button type="warning" disabled>人工接管按钮占位</el-button>
    </div>

    <el-empty v-if="!loading && !errorMessage && !detail.task_id" description="暂无RPA任务详情" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchRpaTaskDetail } from '../../api/rpa';

const route = useRoute();
const detail = ref({});
const loading = ref(false);
const errorMessage = ref('');
const warningMessage = ref('');
const dataStatus = ref('loading');

const statusTagType = computed(() => {
  if (dataStatus.value === 'mock') return 'info';
  if (dataStatus.value === 'fallback') return 'warning';
  if (dataStatus.value === 'error') return 'danger';
  return 'success';
});

const logs = computed(() => {
  if (Array.isArray(detail.value.logs)) return detail.value.logs;
  if (Array.isArray(detail.value.result?.logs)) return detail.value.result.logs;
  return [];
});

const screenshots = computed(() => {
  if (Array.isArray(detail.value.screenshots)) return normalizeScreenshots(detail.value.screenshots);
  if (Array.isArray(detail.value.result?.screenshots)) return normalizeScreenshots(detail.value.result.screenshots);
  return [];
});

function getDetail(data) {
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

function normalizeScreenshots(value) {
  return value.map((item, index) => {
    if (typeof item === 'string') {
      return {
        screenshot_id: `demo-shot-${index + 1}`,
        step_name: 'demo_placeholder',
        screenshot_url: item,
        message: 'demo screenshot url only'
      };
    }
    return item;
  });
}

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2);
}

function rpaStatusType(status) {
  const typeMap = {
    pending: 'info',
    claimed: 'info',
    running: 'primary',
    success: 'success',
    failed: 'danger',
    retrying: 'warning',
    manual_required: 'warning',
    cancelled: 'info'
  };
  return typeMap[status] || 'info';
}

async function loadRpaTaskDetail() {
  loading.value = true;
  errorMessage.value = '';
  warningMessage.value = '';

  try {
    const response = await fetchRpaTaskDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || 'RPA任务详情接口返回失败');

    detail.value = getDetail(response.data);
    dataStatus.value = response.data?.api_status || response.data?.status || 'api';
    if (response.data?.api_status === 'fallback') {
      warningMessage.value = response.message || 'RPA任务详情接口失败，已显示Mock fallback数据';
    }
  } catch (error) {
    dataStatus.value = 'error';
    errorMessage.value = error?.message || 'RPA任务详情接口请求失败';
    detail.value = {};
  } finally {
    loading.value = false;
  }
}

onMounted(loadRpaTaskDetail);
</script>

<style scoped>
.rpa-page {
  display: grid;
  gap: 16px;
}

.rpa-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-note {
  margin: -8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.json-block {
  max-height: 280px;
  margin: 0;
  overflow: auto;
  color: #111827;
  font-size: 12px;
  line-height: 1.5;
}

.rpa-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
