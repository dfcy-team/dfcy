<template>
  <Phase3DecisionPage
    eyebrow="系统治理"
    title="配置版本"
    subtitle="追踪配置变更、审批、生效与回滚记录。"
    boundary-note="回滚操作仅为阶段3流程占位；真实回滚必须由后端校验权限、审批记录和系统安全下限。"
    :loader="fetchConfigChangeLogs"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="版本记录"
    table-note="旧值与新值仅展示非敏感摘要"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchConfigChangeLogs } from '../../api/configCenter';

const filters = [
  { key: 'change_status', label: '状态', options: [{ label: '待审批', value: 'pending' }, { label: '已批准', value: 'approved' }, { label: '已回滚', value: 'rolled_back' }] },
  { key: 'scope', label: '范围', options: [{ label: '租户级', value: 'tenant' }, { label: '系统级', value: 'system' }] }
];
const columns = [
  { prop: 'id', label: '日志编号', width: 150 }, { prop: 'config_key', label: '配置键', width: 220 }, { prop: 'scope_key', label: '范围' },
  { prop: 'from_version', label: '来源版本' }, { prop: 'to_version', label: '目标版本' },
  { prop: 'action', label: '动作', type: 'status' }, { prop: 'actor_id', label: '操作人', width: 120 }, { prop: 'created_at', label: '操作时间', width: 160 }
];
const rowActions = [
  { label: '审计记录', mode: 'detail' },
  { label: '回滚', permission: 'config.rollback', confirmMessage: '当前仅展示回滚流程，不会改变任何配置。', message: '配置回滚接口尚未提供，当前保持 pending。', type: 'danger' }
];
const detailFields = [
  { prop: 'id', label: '日志编号' }, { prop: 'from_version', label: '来源版本' }, { prop: 'to_version', label: '目标版本' }, { prop: 'masked_detail', label: '脱敏审计信息', type: 'json' }
];
</script>
