<template>
  <section class="marketplace-panel">
    <header class="panel-header">
      <div>
        <h2>店铺授权</h2>
        <p>选择内部店铺后前往平台官方授权页；授权完成前状态保持 pending。</p>
      </div>
      <el-tag type="warning">production-enabled 关闭</el-tag>
    </header>

    <el-alert
      title="此页面不提供 App Secret、access token 或 refresh token 输入框；凭据只进入批准的托管边界。"
      type="warning"
      show-icon
      :closable="false"
    />

    <el-form class="authorization-form" label-position="top" @submit.prevent="startAuthorization">
      <el-form-item label="平台">
        <el-select v-model="form.platform" @change="resetPlatformSelection">
          <el-option label="Shopee" value="shopee" />
          <el-option label="TikTok Shop" value="tiktok" />
        </el-select>
      </el-form-item>
      <el-form-item label="应用配置">
        <el-select v-model="form.integration_config_id" placeholder="选择已审核应用">
          <el-option
            v-for="config in matchingConfigs"
            :key="config.id"
            :label="config.account_alias"
            :value="config.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="内部店铺">
        <el-select v-model="form.store_id" filterable placeholder="选择测试店铺">
          <el-option
            v-for="store in matchingStores"
            :key="store.id"
            :label="`${store.name} (${store.code})`"
            :value="store.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="市场/地区">
        <el-select v-model="form.region">
          <el-option v-for="region in regions" :key="region.value" :label="region.label" :value="region.value" />
        </el-select>
      </el-form-item>
      <el-form-item class="callback-field" label="平台 Callback URL">
        <el-input :model-value="callbackUrl" readonly />
      </el-form-item>
      <el-form-item class="submit-field">
        <el-button
          type="primary"
          native-type="submit"
          :loading="starting"
          :disabled="!canStart"
          :title="startDisabledReason"
        >
          前往官方授权
        </el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="message" :title="message" :type="messageType" show-icon :closable="false" />

    <el-table v-loading="loading" :data="authorizations" border empty-text="暂无店铺授权">
      <el-table-column prop="platform" label="平台" min-width="110" />
      <el-table-column prop="store_name" label="内部店铺" min-width="170" />
      <el-table-column prop="region" label="地区" min-width="90" />
      <el-table-column prop="platform_store_id" label="平台店铺" min-width="150" show-overflow-tooltip />
      <el-table-column label="凭据掩码" min-width="190">
        <template #default="{ row }">{{ credentialMask(row.credential_mask) }}</template>
      </el-table-column>
      <el-table-column prop="credential_reference_version" label="引用版本" min-width="100" />
      <el-table-column label="状态" min-width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ row.status || 'pending' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="expires_at" label="过期时间" min-width="180" />
      <el-table-column label="操作" min-width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canRefresh"
            link
            type="primary"
            :disabled="row.status !== 'active'"
            @click="refreshAuthorization(row)"
          >刷新</el-button>
          <el-button
            v-if="canRevoke"
            link
            type="danger"
            :disabled="row.status === 'revoked'"
            @click="revokeAuthorization(row)"
          >撤销</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import {
  fetchIntegrationConfigs,
  fetchMarketplaceStoreAuthorizations,
  refreshMarketplaceStoreAuthorization,
  revokeMarketplaceStoreAuthorization,
  startMarketplaceStoreAuthorization
} from '../api/integrations';
import { fetchPlatforms, fetchStores } from '../api/masterData';
import { useAuthStore } from '../stores/auth';

const callbackPaths = {
  shopee: '/api/internal/integrations/store-authorizations/oauth/callback/shopee/',
  tiktok: '/api/internal/integrations/store-authorizations/oauth/callback/tiktok/'
};
const regions = [
  { value: 'PH', label: '菲律宾 (PH)' },
  { value: 'TH', label: '泰国 (TH)' },
  { value: 'MY', label: '马来西亚 (MY)' }
];

const auth = useAuthStore();
const loading = ref(false);
const starting = ref(false);
const message = ref('');
const messageType = ref('warning');
const configs = ref([]);
const stores = ref([]);
const platforms = ref([]);
const authorizations = ref([]);
const form = reactive({ platform: 'shopee', integration_config_id: '', store_id: '', region: 'PH' });

const callbackUrl = computed(() => new URL(callbackPaths[form.platform], globalThis.location.origin).toString());
const matchingConfigs = computed(() => configs.value.filter((item) => String(item.platform).toLowerCase() === form.platform));
const platformIds = computed(() => new Set(
  platforms.value.filter((item) => item.platform_type === form.platform).map((item) => item.id)
));
const matchingStores = computed(() => stores.value.filter((item) => platformIds.value.has(item.platform_id)));
const canAuthorize = computed(() => auth.hasPermission('integrations.store.authorize'));
const canRefresh = computed(() => auth.hasPermission('integrations.credential.rotate'));
const canRevoke = computed(() => auth.hasPermission('integrations.store.revoke'));
const isHttps = computed(() => globalThis.location.protocol === 'https:');
const canStart = computed(() => Boolean(
  canAuthorize.value && isHttps.value && form.integration_config_id && form.store_id && form.region
));
const startDisabledReason = computed(() => {
  if (!canAuthorize.value) return '缺少 integrations.store.authorize 权限';
  if (!isHttps.value) return '真实 OAuth 只能从 HTTPS 页面发起';
  if (!form.integration_config_id || !form.store_id) return '请先选择应用配置和内部店铺';
  return '';
});

function rows(response) {
  const data = response?.data;
  if (Array.isArray(data)) return data;
  return data?.results || data?.items || [];
}

function resetPlatformSelection() {
  form.integration_config_id = '';
  form.store_id = '';
}

function credentialMask(value) {
  if (!value || typeof value !== 'object') return '-';
  return [value.credential, value.token].filter(Boolean).join(' / ') || '-';
}

function statusType(status) {
  return { active: 'success', error: 'danger', expired: 'warning', revoked: 'info' }[status] || 'warning';
}

async function loadData() {
  loading.value = true;
  message.value = '';
  const [configResponse, storeResponse, platformResponse, authorizationResponse] = await Promise.all([
    fetchIntegrationConfigs(),
    fetchStores({ page_size: 100 }),
    fetchPlatforms({ page_size: 100 }),
    fetchMarketplaceStoreAuthorizations({ page_size: 100 })
  ]);
  configs.value = rows(configResponse);
  stores.value = rows(storeResponse);
  platforms.value = rows(platformResponse);
  authorizations.value = rows(authorizationResponse);
  const failed = [configResponse, storeResponse, platformResponse, authorizationResponse].find((item) => !item?.success);
  if (failed) {
    message.value = failed.message || '连接配置加载失败';
    messageType.value = 'error';
  }
  loading.value = false;
}

async function startAuthorization() {
  if (!canStart.value) return;
  starting.value = true;
  message.value = '';
  const response = await startMarketplaceStoreAuthorization({
    platform: form.platform,
    integration_config_id: form.integration_config_id,
    store_id: form.store_id,
    region: form.region,
    redirect_uri: callbackUrl.value,
    scopes: []
  });
  starting.value = false;
  if (!response?.success) {
    message.value = response?.message || 'OAuth 发起失败';
    messageType.value = 'error';
    return;
  }
  const authorizationUrl = response.data?.authorization_url;
  if (!authorizationUrl) {
    message.value = '当前是 Mock/Pending 配置，未生成真实平台授权地址。';
    messageType.value = 'warning';
    return;
  }
  globalThis.location.assign(authorizationUrl);
}

async function refreshAuthorization(row) {
  const response = await refreshMarketplaceStoreAuthorization(row.id);
  if (!response?.success) {
    message.value = response?.message || '刷新失败';
    messageType.value = 'error';
    return;
  }
  await loadData();
}

async function revokeAuthorization(row) {
  try {
    await ElMessageBox.confirm(`确认撤销 ${row.store_name || '当前店铺'} 的平台授权？`, '撤销授权', { type: 'warning' });
  } catch (error) {
    if (error === 'cancel' || error === 'close') return;
    throw error;
  }
  const response = await revokeMarketplaceStoreAuthorization(row.id);
  if (!response?.success) {
    message.value = response?.message || '撤销失败';
    messageType.value = 'error';
    return;
  }
  await loadData();
}

onMounted(loadData);
</script>

<style scoped>
.marketplace-panel { display: grid; gap: 16px; margin-top: 24px; }
.panel-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.panel-header h2 { margin: 0; font-size: 18px; }
.panel-header p { margin: 6px 0 0; color: #64748b; font-size: 13px; }
.authorization-form { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 0 12px; padding: 16px; border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; }
.callback-field { grid-column: span 3; }
.submit-field { align-self: end; }
@media (max-width: 960px) {
  .authorization-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .callback-field { grid-column: span 2; }
}
@media (max-width: 640px) {
  .panel-header { display: grid; }
  .authorization-form { grid-template-columns: 1fr; }
  .callback-field { grid-column: span 1; }
}
</style>
