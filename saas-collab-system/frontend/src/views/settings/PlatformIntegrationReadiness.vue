<template>
  <Phase2DataPage
    title="平台接入准备度"
    note="展示当前租户各平台的真实只读接入条件与待处理项。"
    risk-note="本页只读取实际配置状态，不会启用平台写入、修改密钥或发起授权。生产写入始终关闭。"
    :loader="fetchPlatformIntegrationReadiness"
    :columns="columns"
    :filters="['平台', '当前接入状态']"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchPlatformIntegrationReadiness } from '../../api/integrations';

const columns = [
  { prop: 'platform', label: '平台' },
  { prop: 'current_access_status_label', label: '当前接入状态', type: 'status', width: 170 },
  { prop: 'mock_sandbox_status_label', label: '测试环境状态', type: 'status', width: 180 },
  { prop: 'production_status_label', label: '生产状态', type: 'status', width: 170 },
  { prop: 'config_summary', label: '配置概况', width: 210 },
  { prop: 'blocker_summary', label: '待处理项', minWidth: 360 },
  { prop: 'security_review_done', label: '安全评审' },
  { prop: 'credential_custody_done', label: '密钥托管' },
  { prop: 'network_isolation_done', label: '网络隔离' },
  { prop: 'high_risk_action_allowed', label: '高风险动作' }
];
</script>
