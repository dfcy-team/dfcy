<template>
  <RPAResourcePage title="异常中心" note="集中处理销售、库存、财务及其他业务核查事项。"
    boundary-note="异常处置只更新异常闭环状态，不修改原业务记录，也不触发真实自动化任务或资金操作。"
    :loader="fetchWorkflowExceptions" :columns="columns" :filters="filters" :row-actions="actions" :value-labels="valueLabels" empty-text="暂无授权范围内的异常" />
</template>

<script setup>
import RPAResourcePage from '../../components/RPAResourcePage.vue';
import { ElMessageBox } from 'element-plus';
import { assignWorkflowException, closeWorkflowException, fetchWorkflowExceptions, resolveWorkflowException } from '../../api/workflow';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const modules = [
  { value: 'product', label: '商品' }, { value: 'purchasing', label: '采购' }, { value: 'supplier', label: '供应商' },
  { value: 'listing', label: '刊登' }, { value: 'finance', label: '财务' }, { value: 'rpa', label: '自动化' },
  { value: 'integration', label: '集成' }, { value: 'inventory', label: '库存' }, { value: 'sales', label: '销售' }
];
const statuses = [
  { value: 'open', label: '待处理' }, { value: 'assigned', label: '处理中' },
  { value: 'resolved', label: '已解决' }, { value: 'closed', label: '已关闭' }
];
const valueLabels = {
  connection: { connected: '已连接', loading: '读取中', error: '读取失败', degraded: '连接异常', fallback: '读取失败', mock: '示例数据' },
  audit: { create: '创建核查', assign: '分配负责人', resolve: '填写处理结果', close: '关闭' },
  module: Object.fromEntries(modules.map(option => [option.value, option.label])),
  status: Object.fromEntries(statuses.map(option => [option.value, option.label])),
  severity: { low: '低', medium: '中', high: '高', critical: '严重' },
  business_type: { report_group: '报表分组', order: '订单', purchase_order: '采购单', supplier: '供应商', product: '商品' }
};
async function resolveWithNote(row) {
  const { value } = await ElMessageBox.prompt('填写本次处理结果说明（必填）', '解决异常', { inputType: 'textarea', inputValidator: value => Boolean(value?.trim()), inputErrorMessage: '请填写处理结果说明' });
  const resolution = value.trim();
  if (!resolution) throw new Error('请填写处理结果说明');
  return resolveWorkflowException(row.id, { resolution });
}

const filters = [
  { key: 'module', label: '模块', options: modules },
  { key: 'status', label: '状态', options: statuses }
];
const columns = [
  { prop: 'title', label: '异常主题', width: 220 }, { prop: 'module', label: '模块' },
  { prop: 'severity', label: '级别', type: 'status' }, { prop: 'status', label: '状态', type: 'status' },
  { prop: 'assigned_to_id', label: '负责人' }, { prop: 'business_id', label: '业务ID', width: 150 },
  { prop: 'created_at', label: '发现时间', width: 180 }
];
const actions = [
  { label: '详情', permission: 'workflow.exceptions.view', route: (row) => `/workflow/exceptions/${row.id}` },
  { label: '分配给我', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '确认由当前登录用户处理此异常？', handler: (row) => assignWorkflowException(row.id, { assignee_id: auth.currentUser?.user_id }) },
  { label: '解决', permission: 'workflow.exceptions.manage', disabled: (row) => !['open', 'assigned'].includes(row.status), confirmMessage: '需填写本次处理结果说明；不修改原业务数据。', handler: resolveWithNote },
  { label: '关闭', permission: 'workflow.exceptions.manage', disabled: (row) => row.status !== 'resolved', confirmMessage: '确认关闭已解决异常？', handler: (row) => closeWorkflowException(row.id) }
];
</script>
