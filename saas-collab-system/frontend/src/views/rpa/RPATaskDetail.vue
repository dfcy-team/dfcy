<template>
  <section class="fix-page">
    <header class="fix-header">
      <div>
        <h1 class="page-title">RPA任务详情</h1>
        <p>GET /api/internal/rpa/tasks/{id}/；任务状态与运行状态分离。</p>
      </div>
      <el-tag :type="tagType">{{ status }}</el-tag>
    </header>

    <el-alert title="人工分配和 Mock 重试均由后端权限与状态机校验；不触发真实浏览器或平台。" type="info" show-icon :closable="false" />
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
        <el-table-column prop="created_at" label="时间" min-width="170" />
        <el-table-column prop="status" label="状态" min-width="90" />
        <el-table-column prop="step_name" label="步骤" min-width="150" />
        <el-table-column prop="message" label="消息" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>screenshots 占位展示</template>
      <el-table :data="screenshots" border empty-text="暂无截图占位">
        <el-table-column prop="step_name" label="节点" min-width="150" />
        <el-table-column prop="placeholder_url" label="demo / 占位引用" min-width="260" show-overflow-tooltip />
        <el-table-column prop="payload_hash" label="Payload Hash" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <div class="fix-actions">
      <el-button
        type="warning"
        :disabled="!canManage || !['failed', 'manual_required'].includes(detail.status)"
        @click="retryTask"
      >Mock重试</el-button>
      <el-button
        :disabled="!canManage || detail.status !== 'manual_required'"
        @click="assignManual"
      >分配给我</el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRoute } from 'vue-router';
import { assignRpaManual, fetchRpaTaskDetail, retryRpaMock } from '../../api/rpa';
import { useMock } from '../../api/request';
import { useAuthStore } from '../../stores/auth';

const route = useRoute();
const auth = useAuthStore();
const detail = ref({});
const loading = ref(false);
const status = ref('loading');
const message = ref('');
const tagType = computed(() => (status.value === 'error' ? 'danger' : status.value === 'fallback' ? 'warning' : 'info'));
const logs = computed(() => (Array.isArray(detail.value.logs) ? detail.value.logs : []));
const screenshots = computed(() => (Array.isArray(detail.value.screenshots) ? detail.value.screenshots : []));
const canManage = computed(() => auth.hasPermission('rpa.tasks.manage'));

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

async function runAction(confirmMessage, handler) {
  try {
    await ElMessageBox.confirm(confirmMessage, '确认受控操作', { type: 'warning' });
    const response = await handler();
    if (!response?.success) throw new Error(response?.message || '操作失败');
    ElMessage.success(response.message || '操作完成');
    await loadDetail();
  } catch (error) {
    if (error === 'cancel') return;
    ElMessage.error(error?.message || '操作失败');
  }
}

const retryTask = () => runAction(
  '仅将任务放回 Mock/dry-run 队列，不连接真实平台。',
  () => retryRpaMock(detail.value.id)
);
const assignManual = () => runAction(
  '仅分配人工检查责任，不执行平台动作。',
  () => assignRpaManual(detail.value.id, { reason: 'Assigned from task detail.' })
);

async function loadDetail() {
  loading.value = true;
  try {
    const response = await fetchRpaTaskDetail(route.params.id || 1);
    if (!response.success) throw new Error(response.message || 'RPA任务详情接口失败');
    detail.value = getDetail(response.data);
    status.value = response.data?.api_status || (useMock ? 'mock' : 'connected');
    if (response.data?.api_status === 'fallback') message.value = response.message;
  } catch (error) {
    status.value = 'error';
    message.value = error?.message || 'RPA任务详情请求失败';
  } finally {
    loading.value = false;
  }
}

onMounted(loadDetail);
</script>

<style scoped>
.fix-page { display: grid; gap: 16px; }
.fix-header { display: flex; justify-content: space-between; gap: 16px; }
.fix-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
pre { max-height: 260px; margin: 0; overflow: auto; font-size: 12px; line-height: 1.5; }
.fix-actions { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
