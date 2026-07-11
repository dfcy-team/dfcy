<template>
  <Phase2DataPage
    title="平台接入准备度"
    note="展示未来真实平台接入前的只读准备度状态；生产接入默认 disabled。"
    risk-note="阶段2仅允许 Mock 或后端返回的只读状态，不允许启用真实生产平台。"
    :loader="mockPlatformIntegrationReadiness"
    :columns="columns"
    :filters="['平台', '准备状态']"
    :actions="['准备度复核占位', '生产启用禁用']"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { mockPlatformIntegrationReadiness } from '../../mock/platformRisk';

const columns = [
  { prop: 'platform', label: '平台' },
  { prop: 'current_access_status', label: '当前接入状态', type: 'status', width: 170 },
  { prop: 'mock_sandbox_status', label: 'Mock/Sandbox状态', type: 'status', width: 180 },
  { prop: 'production_status', label: '生产状态', type: 'status', width: 170 },
  { prop: 'security_review_done', label: '安全评审' },
  { prop: 'credential_custody_done', label: '密钥托管' },
  { prop: 'network_isolation_done', label: '网络隔离' },
  { prop: 'permission_audit_done', label: '权限审计' },
  { prop: 'rollback_plan_done', label: '回滚方案' },
  { prop: 'gray_release_done', label: '灰度方案' },
  { prop: 'high_risk_action_allowed', label: '高风险动作' }
];
</script>
