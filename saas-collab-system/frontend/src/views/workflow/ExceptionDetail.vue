<template>
  <section class="exception-detail"><el-alert v-if="sourceError" :title="sourceError" type="warning" :closable="false" /><el-button v-if="sourceAvailable" type="primary" plain @click="returnToReport">返回报表来源</el-button><WorkflowDetailPage title="异常详情" subtitle="查看异常上下文、处理结果和审计时间线。"
    boundary-note="关闭动作只能用于已解决异常；异常页面不直接修改业务主数据。"
    :loader="loadException" :fields="fields" :actions="actions" :value-labels="valueLabels" /></section>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import { ref } from 'vue';
import WorkflowDetailPage from '../../components/WorkflowDetailPage.vue';
import { assignWorkflowException, closeWorkflowException, fetchWorkflowException, resolveWorkflowException } from '../../api/workflow';
import { fetchReportExceptionSource } from '../../api/reportCollaboration';
import { useAuthStore } from '../../stores/auth';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const sourceAvailable = ref(false), sourceError = ref('');
let detailSequence = 0;
const valueLabels = {
  connection: { connected: '已连接', loading: '读取中', error: '读取失败', degraded: '连接异常', fallback: '读取失败', mock: '示例数据' },
  audit: { create: '创建核查', assign: '分配负责人', resolve: '填写处理结果', close: '关闭' },
  module: { product: '商品', purchasing: '采购', supplier: '供应商', listing: '刊登', finance: '财务', rpa: '自动化', integration: '集成', inventory: '库存', sales: '销售' },
  status: { open: '待处理', assigned: '处理中', resolved: '已解决', closed: '已关闭' },
  severity: { low: '低', medium: '中', high: '高', critical: '严重' },
  business_type: { report_group: '报表分组', order: '订单', purchase_order: '采购单', supplier: '供应商', product: '商品' }
};
async function loadException() {
  const sequence = ++detailSequence;
  sourceAvailable.value = false;
  sourceError.value = '';
  const response = await fetchWorkflowException(route.params.id);
  if (!response?.success) return response;
  if (response.data?.business_type === 'report_group') {
    try {
      const source = await fetchReportExceptionSource(route.params.id);
      if (sequence === detailSequence && source?.success && source.data?.source?.config) sourceAvailable.value = true;
      else if (sequence === detailSequence) sourceError.value = '报表来源核查未通过，已隐藏回跳入口。';
    } catch { if (sequence === detailSequence) sourceError.value = '报表来源核查失败，已隐藏回跳入口。'; }
  }
  return response;
}
function returnToReport() {
  if (sourceAvailable.value) router.push({ path: '/reports/basic', query: { tab: 'analysis', source_exception: String(route.params.id) } });
}
async function resolveWithNote(row) {
  const { value } = await ElMessageBox.prompt('填写本次处理结果说明（必填）', '解决异常', { inputType: 'textarea', inputValidator: value => Boolean(value?.trim()), inputErrorMessage: '请填写处理结果说明' });
  const resolution = value.trim();
  if (!resolution) throw new Error('请填写处理结果说明');
  return resolveWorkflowException(row.id, { resolution });
}
const fields = [
  { prop: 'module', label: '模块' }, { prop: 'title', label: '异常主题' },
  { prop: 'severity', label: '级别', type: 'status' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'business_type', label: '业务类型' }, { prop: 'business_id', label: '业务标识' },
  { prop: 'assigned_to_id', label: '负责人' }, { prop: 'description', label: '异常说明' },
  { prop: 'resolution', label: '解决记录' }, { prop: 'created_at', label: '发现时间' }
];
const actions = [
  { label: '分配给我', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '确认由当前登录用户处理此异常？', handler: (row) => assignWorkflowException(row.id, { assignee_id: auth.currentUser?.user_id }) },
  { label: '解决', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '仅更新异常闭环状态。', handler: resolveWithNote },
  { label: '关闭', permission: 'workflow.exceptions.manage', disabled: (row) => row.status !== 'resolved', confirmMessage: '确认关闭？', handler: (row) => closeWorkflowException(row.id) }
];
</script>
<style scoped>.exception-detail { display: grid; gap: 12px; }</style>
