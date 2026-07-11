<template>
  <Phase2DataPage
    title="平台接入配置"
    note="GET /api/internal/integrations/configs/，当前仅 Mock/Sandbox 占位"
    risk-note="生产环境配置未通过专项评审，不可启用；页面不展示明文凭据。"
    :loader="fetchIntegrationConfigs"
    :filters="['平台', '状态', '环境']"
    :columns="columns"
    empty-text="暂无平台配置"
  />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import { fetchIntegrationConfigs } from '../../api/integrations';

const columns = [
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
