<template>
  <section class="workflow-detail">
    <header>
      <div><h1>{{ title }}</h1><p>{{ subtitle }}</p></div>
      <el-tag :type="statusType(detail.status)">{{ detail.status || connectionState }}</el-tag>
    </header>
    <el-alert :title="boundaryNote" type="warning" show-icon :closable="false" />
    <el-alert v-if="message" :title="message" :type="connectionState === 'error' ? 'error' : 'warning'" show-icon :closable="false" />
    <el-card v-loading="loading" shadow="never">
      <el-descriptions :column="2" border>
        <el-descriptions-item v-for="field in fields" :key="field.prop" :label="field.label">
          <pre v-if="field.type === 'json'">{{ JSON.stringify(detail[field.prop] || {}, null, 2) }}</pre>
          <el-tag v-else-if="field.type === 'status'" :type="statusType(detail[field.prop])">{{ detail[field.prop] || '-' }}</el-tag>
          <span v-else>{{ formatValue(detail[field.prop]) }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
    <el-card shadow="never">
      <template #header>状态与审计时间线</template>
      <el-timeline v-if="auditEvents.length">
        <el-timeline-item v-for="event in auditEvents" :key="event.id || `${event.action}-${event.created_at}`" :timestamp="event.created_at">
          {{ event.action }}：{{ event.from_status || '-' }} → {{ event.to_status || '-' }}
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无审计事件" />
    </el-card>
    <div class="actions">
      <el-button v-for="action in visibleActions" :key="action.label" :type="action.type || 'primary'"
        :disabled="actionAccess(action).disabled || (typeof action.disabled === 'function' && action.disabled(detail))"
        @click="runAction(action)">{{ action.label }}</el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useAuthStore } from '../stores/auth';
import { getActionAccess } from '../utils/actionAccess';

const props = defineProps({
  title: { type: String, required: true }, subtitle: { type: String, default: '' }, boundaryNote: { type: String, required: true },
  loader: { type: Function, required: true }, fields: { type: Array, default: () => [] }, actions: { type: Array, default: () => [] }
});
const auth = useAuthStore();
const detail = ref({});
const loading = ref(false);
const message = ref('');
const connectionState = ref('loading');
const auditEvents = computed(() => Array.isArray(detail.value.audit_events) ? detail.value.audit_events : []);
const actionAccess = (action) => getActionAccess(auth, action);
const visibleActions = computed(() => props.actions.filter((action) => actionAccess(action).visible));
const statusType = (value) => ({ approved: 'success', confirmed: 'success', resolved: 'success', closed: 'info', rejected: 'danger', pending: 'warning', pending_confirmation: 'warning', open: 'danger', assigned: 'primary', withdrawn: 'info' }[value] || 'info');
const formatValue = (value) => Array.isArray(value) ? value.join(', ') : value ?? '-';

async function load() {
  loading.value = true;
  message.value = '';
  try {
    const response = await props.loader();
    if (!response?.success) throw new Error(response?.message || '详情加载失败');
    detail.value = response.data || {};
    connectionState.value = response.data?.api_status || (response.data?.status === 'mock' ? 'mock' : 'connected');
  } catch (error) {
    connectionState.value = 'error';
    message.value = error?.message || '详情加载失败';
  } finally { loading.value = false; }
}

async function runAction(action) {
  const access = actionAccess(action);
  if (!access.allowed) return ElMessage.warning(access.reason);
  try {
    await ElMessageBox.confirm(action.confirmMessage, action.confirmTitle || '确认受控操作', { type: action.confirmType || 'warning' });
    const response = await action.handler(detail.value);
    if (!response?.success) throw new Error(response?.message || '操作失败');
    ElMessage.success(response.message || '操作完成');
    await load();
  } catch (error) {
    if (error === 'cancel' || error === 'close') return;
    ElMessage.error(error?.message || '操作失败');
  }
}

onMounted(load);
</script>

<style scoped>
.workflow-detail { display: grid; gap: 16px; }
header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
h1 { margin: 0; color: #172033; font-size: 24px; }
header p { margin: 7px 0 0; color: #64748b; font-size: 13px; }
pre { max-height: 260px; margin: 0; overflow: auto; white-space: pre-wrap; font-size: 12px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 720px) { :deep(.el-descriptions__body .el-descriptions__table) { table-layout: fixed; } }
</style>
