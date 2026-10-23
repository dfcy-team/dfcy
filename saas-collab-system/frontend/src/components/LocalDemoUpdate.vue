<template>
  <div v-if="visible" class="local-demo-update" aria-live="polite">
    <el-tooltip content="更新会切换到新演示数据库；旧测试库中的手工修改仍保留在旧库，不会合并到新库。" placement="bottom">
      <el-button
        size="small"
        type="primary"
        :loading="busy"
        :disabled="busy"
        @click="startUpdate"
      >更新演示数据</el-button>
    </el-tooltip>
    <el-button
      v-if="previousAvailable && !busy"
      size="small"
      :loading="rollingBack"
      :disabled="rollingBack"
      @click="rollback"
    >回滚演示数据</el-button>
    <span v-if="statusText" class="local-demo-update__status" role="status">{{ statusText }}</span>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { requestApi } from '../api/request';

const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 800;
const BUSY_STATUSES = new Set(['queued', 'fetching', 'preparing', 'activating']);

const visible = ref(false);
const status = ref('idle');
const errorCode = ref('');
const previousAvailable = ref(false);
const busy = ref(false);
const rollingBack = ref(false);
const activeUpdate = ref(false);
const pollCount = ref(0);
const notice = ref('');
const statusText = computed(() => {
  if (notice.value) return notice.value;
  if (status.value === 'failed') return `更新失败，可重试${errorCode.value ? `（${errorCode.value}）` : ''}`;
  if (status.value === 'ready') return '演示数据已更新';
  if (status.value === 'queued') return '更新任务已排队';
  if (status.value === 'fetching') return '正在获取演示数据…';
  if (status.value === 'preparing') return '正在准备演示数据库…';
  if (status.value === 'activating') return '正在切换演示数据库…';
  return '';
});

let pollTimer = null;
let disposed = false;
let generation = 0;

function applyData(data) {
  if (!data || typeof data !== 'object' || data.enabled !== true) return false;
  visible.value = true;
  status.value = typeof data.status === 'string' ? data.status : 'idle';
  errorCode.value = data.error_code || '';
  previousAvailable.value = data.previous_available === true;
  return true;
}

function clearPoll() {
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = null;
}

function finishUpdate() {
  busy.value = false;
  rollingBack.value = false;
  activeUpdate.value = false;
  clearPoll();
}

function failUpdate(error = '') {
  errorCode.value = error;
  status.value = 'failed';
  finishUpdate();
}

function queuePoll(token) {
  if (disposed || !busy.value || token !== generation) return;
  if (pollCount.value >= MAX_POLLS) {
    failUpdate('POLL_TIMEOUT');
    return;
  }
  pollTimer = setTimeout(() => poll(token), POLL_INTERVAL_MS);
}

async function poll(token) {
  if (disposed || !busy.value || token !== generation) return;
  pollTimer = null;
  pollCount.value += 1;
  const response = await requestApi({ url: '/__demo_update/status', method: 'get', noMockFallback: true });
  if (disposed || token !== generation) return;
  if (!response?.success) {
    // The runtime restarts the backend briefly while replacing the database.
    if (response?.http_status === 503) {
      queuePoll(token);
      return;
    }
    failUpdate(response?.code || 'REQUEST_FAILED');
    return;
  }
  if (!applyData(response.data)) {
    failUpdate('INVALID_STATUS');
    return;
  }
  if (status.value === 'ready') {
    const shouldReload = activeUpdate.value;
    finishUpdate();
    if (shouldReload && !disposed) window.location.reload();
    return;
  }
  if (status.value === 'failed') {
    finishUpdate();
    return;
  }
  if (BUSY_STATUSES.has(status.value)) {
    queuePoll(token);
    return;
  }
  finishUpdate();
}

async function submitAction(action) {
  if (!visible.value || busy.value || rollingBack.value) return;
  clearPoll();
  const token = ++generation;
  busy.value = true;
  rollingBack.value = action === 'rollback';
  activeUpdate.value = true;
  pollCount.value = 0;
  errorCode.value = '';
  notice.value = '';
  status.value = 'queued';
  const response = await requestApi({ url: `/__demo_update/${action}`, method: 'post' });
  if (disposed || token !== generation) return;
  if (!response?.success || !applyData(response.data)) {
    failUpdate(response?.code || 'REQUEST_FAILED');
    return;
  }
  if (status.value === 'ready') {
    finishUpdate();
    window.location.reload();
    return;
  }
  if (status.value === 'failed') {
    finishUpdate();
    return;
  }
  queuePoll(token);
}

function startUpdate() { return submitAction('start'); }

function rollback() {
  if (!previousAvailable.value) return;
  return submitAction('rollback');
}

onMounted(async () => {
  const response = await requestApi({ url: '/__demo_update/status', method: 'get', noMockFallback: true });
  if (disposed) return;
  if (!response?.success || !applyData(response.data)) return;
  // Existing work may be observed after a refresh. Its ready state must not
  // trigger a reload. An observed in-progress update still reloads on completion.
  if (BUSY_STATUSES.has(status.value)) {
    busy.value = true;
    activeUpdate.value = true;
    pollCount.value = 0;
    queuePoll(++generation);
  }
});

onBeforeUnmount(() => {
  disposed = true;
  generation += 1;
  clearPoll();
});
</script>

<style scoped>
.local-demo-update { display: flex; align-items: center; gap: 8px; }
.local-demo-update__status { color: #64748b; font-size: 12px; white-space: nowrap; }
</style>
