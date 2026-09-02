<template>
  <Phase3DecisionPage
    ref="pageRef"
    eyebrow="系统治理"
    title="配置版本"
    subtitle="追踪配置变更、审批、生效与回滚记录。"
    boundary-note="回滚会基于选定的历史版本创建新的不可变版本；后端会再次校验 tenant、data_scope、回滚权限和审计记录。"
    :loader="loadHistory"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="版本记录"
    table-note="历史版本不可修改；回滚只新增版本，不覆盖原始审计记录"
  />
</template>

<script setup>
import { ref } from 'vue';
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchConfigChangeLogs, rollbackConfigValue } from '../../api/configCenter';

const pageRef = ref(null);
const filters = [
  { key: 'scope', label: '范围', options: [{ label: '租户级', value: 'tenant' }, { label: '系统级', value: 'system' }] }
];
const columns = [
  { prop: 'id', label: '日志编号', width: 150 },
  { prop: 'config_key', label: '配置键', width: 220 },
  { prop: 'scope_key', label: '范围' },
  { prop: 'from_version', label: '来源版本' },
  { prop: 'to_version', label: '目标版本' },
  { prop: 'action', label: '动作', type: 'status' },
  { prop: 'actor_id', label: '操作人', width: 120 },
  { prop: 'created_at', label: '操作时间', width: 180 }
];
const rowActions = [
  { label: '审计记录', mode: 'detail' },
  {
    label: '回滚此版本',
    permission: 'config.rollback',
    type: 'danger',
    when: (row) => Boolean(row.version_id),
    confirmMessage: '确认以该历史版本创建新的配置版本？原始版本和审计记录不会被覆盖。',
    execute: (row) => rollbackConfigValue(row.version_id, { effective_at: new Date().toISOString() }),
    successMessage: '回滚版本已创建，结果已记录审计。'
  }
];
const detailFields = [
  { prop: 'id', label: '日志编号' },
  { prop: 'version_id', label: '版本记录 ID' },
  { prop: 'from_version', label: '来源版本' },
  { prop: 'to_version', label: '目标版本' },
  { prop: 'action', label: '动作' },
  { prop: 'masked_detail', label: '脱敏审计信息', type: 'json' }
];

async function loadHistory(query = {}) {
  return fetchConfigChangeLogs({ ...query, page: 1, page_size: 100 });
}
</script>
