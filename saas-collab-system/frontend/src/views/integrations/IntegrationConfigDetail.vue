<template>
  <Phase2DataPage
    title="平台接入配置详情"
    note="GET /api/internal/integrations/configs/{id}/"
    risk-note="不提供查看完整密钥、真实连接测试或生产启用按钮。"
    mode="detail"
    :loader="() => fetchIntegrationConfigDetail(route.params.id || 1)"
    :detail-fields="fields"
    :action-configs="actionConfigs"
    empty-text="暂无配置详情"
  />
</template>

<script setup>
import { useRoute } from 'vue-router';
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { disableIntegrationConfig, fetchIntegrationConfigDetail, verifyIntegrationConfig } from '../../api/integrations';

const route = useRoute();
const actionConfigs = [
  {
    label: 'Sandbox验证',
    permission: 'integrations.manage',
    confirmMessage: '仅执行Mock/Sandbox验证；production配置将由后端拒绝。',
    handler: () => verifyIntegrationConfig(route.params.id || 1)
  },
  {
    label: '禁用配置',
    permission: 'integrations.manage',
    type: 'danger',
    confirmMessage: '确认禁用当前配置？此操作不会连接真实平台。',
    handler: () => disableIntegrationConfig(route.params.id || 1)
  }
];
const fields = [
  { prop: 'platform', label: '平台' },
  { prop: 'account_alias', label: '账号别名' },
  { prop: 'environment', label: '环境' },
  { prop: 'status', label: '状态', type: 'status' },
  { prop: 'credential_fingerprint', label: '凭据指纹' },
  { prop: 'credential_key_version', label: '密钥版本' },
  { prop: 'last_verified_at', label: '最后验证' },
  { prop: 'updated_at', label: '更新时间' }
];
</script>
