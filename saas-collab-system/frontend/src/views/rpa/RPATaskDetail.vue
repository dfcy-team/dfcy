<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">RPA任务详情</h1>
        <p>管理查询 pending: GET /api/internal/rpa/tasks/{id}/；不调用 Agent 执行接口。</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="重试/人工接管按钮仅为 pending/mock 占位，不触发真实执行，不连接真实 BigSeller。" type="info" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="status === 'error' ? 'error' : 'warning'" show-icon :closable="false" />

    <el-card v-loading="loading" shadow="never">
      <template #header>任务基础信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务编号">{{ detail.task_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="任务类型">{{ detail.task_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="业务类型">{{ detail.business_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="业务ID">{{ detail.business_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态"><el-tag :type="rpaStatusType(detail.status)">{{ detail.status || '-' }}</el-tag></el-descriptions-item>
        <el-descriptions-item label="Agent">{{ detail.agent || '-' }}</el-descriptions-item>
        <el-descriptions-item label="重试次数">{{ detail.retry_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="人工接管">{{ detail.manual_required ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="错误原因">{{ detail.error_message || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never"><template #header>payload JSON</template><pre>{{ formatJson(detail.payload) }}</pre></el-card>
    <el-card shadow="never"><template #header>result JSON</template><pre>{{ formatJson(detail.result) }}</pre></el-card>

    <el-card shadow="never">
      <template #header>logs 占位展示</template>
      <el-table :data="logs" border empty-text="暂无日志">
        <el-table-column prop="occurred_at" label="时间" min-width="170" />
        <el-table-column prop="level" label="级别" min-width="90" />
        <el-table-column prop="step_name" label="步骤" min-width="150" />
        <el-table-column prop="message" label="消息" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>screenshots 占位展示</template>
      <el-table :data="screenshots" border empty-text="暂无截图占位">
        <el-table-column prop="step_name" label="节点" min-width="150" />
        <el-table-column prop="screenshot_url" label="demo URL / 占位引用" min-width="260" show-overflow-tooltip />
        <el-table-column prop="message" label="说明" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <div class="fix-actions">
      <el-button disabled>重试 pending</el-button>
      <el-button type="warning" disabled>人工接管 pending</el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchRpaTaskDetail } from '../../api/rpa';

const route = useRoute();
const detail = ref({});
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));
const logs = computed(() => (Array.isArray(detail.value.logs) ? detail.value.logs : []));
const screenshots = computed(() => (Array.isArray(detail.value.screenshots) ? detail.value.screenshots : []));

function getDetail(data) {
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

function formatJson(value) {
  return JSON.stringify(value || {}, null, 2);
}

function rpaStatusType(value) {
  return { success: 'success', failed: 'danger', retrying: 'warning', manual_required: 'warning', running: 'primary' }[value] || 'info';
}

onMounted(async () => {
  loading.value = true;
  try {
    const response = await fetchRpaTaskDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || 'RPA任务详情接口失败');
    detail.value = getDetail(response.data);
    status.value = response.data?.api_status || response.data?.status || 'mock';
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || 'RPA任务详情请求失败';
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
pre { max-height: 260px; margin: 0; overflow: auto; font-size: 12px; line-height: 1.5; }
.fix-actions { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
