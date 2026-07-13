<template>
  <Phase3DecisionPage
    eyebrow="系统治理"
    title="配置中心"
    subtitle="查看配置草稿、范围、版本、生效与审批状态。"
    boundary-note="配置中心不提供真实平台密钥、银行密码、Cookie、Session 或明文 Token 输入；敏感项仅展示引用状态或脱敏摘要。"
    :loader="fetchConfigItems"
    :filters="filters"
    :columns="columns"
    :row-actions="rowActions"
    :detail-fields="detailFields"
    table-title="配置项"
    table-note="tenant 配置不得覆盖系统安全下限"
  />
</template>

<script setup>
import Phase3DecisionPage from '../../components/Phase3DecisionPage.vue';
import { fetchConfigItems } from '../../api/configCenter';

const filters = [
  { key: 'scope', label: '范围', options: [{ label: '租户级', value: 'tenant' }, { label: '系统级', value: 'system' }] },
  { key: 'approval_status', label: '审批状态', options: [{ label: '草稿', value: 'draft' }, { label: '待审批', value: 'pending' }, { label: '已批准', value: 'approved' }] }
];
const columns = [
  { prop: 'config_key', label: '配置键', width: 220 }, { prop: 'display_name', label: '配置名称', width: 160 }, { prop: 'scope', label: '范围' },
  { prop: 'value_summary', label: '当前值摘要', width: 190 }, { prop: 'default_summary', label: '默认值摘要', width: 140 },
  { prop: 'version', label: '版本' }, { prop: 'approval_status', label: '审批', type: 'status' }, { prop: 'effective_at', label: '生效时间', width: 160 }
];
const rowActions = [
  { label: '治理信息', mode: 'detail' },
  { label: '提交审批', confirmMessage: '当前只展示配置审批流程，不会提交真实配置变更。', message: '配置审批接口尚未提供，当前保持 pending。' }
];
const detailFields = [
  { prop: 'config_key', label: '配置键' }, { prop: 'value_summary', label: '当前值摘要' }, { prop: 'sensitive', label: '敏感配置' }, { prop: 'governance', label: '治理与审批', type: 'json' }
];
</script>
