<template>
  <Phase2DataPage
    title="平台接入配置"
    note="Shopee / TikTok Shop 应用配置；页面不接收或展示 App Secret、Token"
    risk-note="真实连接默认关闭；只有固定制品、凭据托管和平台合同均获批后才能发起真实网络请求。"
    :loader="fetchIntegrationConfigs"
    :filters="['平台', '状态', '环境']"
    :columns="columns"
    empty-text="暂无平台配置"
  />
  <MarketplaceAuthorizationPanel />
</template>

<script setup>
import Phase2DataPage from '../../components/Phase2DataPage.vue';
import MarketplaceAuthorizationPanel from '../../components/MarketplaceAuthorizationPanel.vue';
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
