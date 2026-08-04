<template>
  <section class="oauth-page">
    <header class="oauth-header">
      <div>
        <h1 class="page-title">平台授权</h1>
        <p>仅使用后端返回的授权地址；当前为 synthetic/mock，未连接真实平台。</p>
      </div>
      <el-tag :type="statusTagType">{{ statusLabel }}</el-tag>
    </header>

    <el-alert
      title="真实 OAuth 网络默认关闭。页面不保存授权地址、state、callback query、code 或凭据。"
      type="warning"
      show-icon
      :closable="false"
    />

    <el-card shadow="never">
      <template #header>发起授权</template>
      <el-form :model="form" label-width="150px" @submit.prevent="startAuthorization">
        <el-form-item label="平台">
          <el-select v-model="form.platform" style="width: 220px">
            <el-option label="Shopee" value="shopee" />
            <el-option label="TikTok Shop" value="tiktok" />
          </el-select>
        </el-form-item>
        <el-form-item label="集成配置 ID"><el-input v-model="form.integration_config_id" /></el-form-item>
        <el-form-item label="店铺 ID"><el-input v-model="form.store_id" /></el-form-item>
        <el-form-item label="区域"><el-input v-model="form.region" maxlength="8" /></el-form-item>
        <el-form-item label="回跳目标"><el-input model-value="integrations" disabled /></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="startAuthorization">发起授权</el-button>
          <el-button :loading="loading" @click="loadAttempt" :disabled="!attemptId">查询状态</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>Attempt 状态</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="Attempt ID">{{ attemptId || '-' }}</el-descriptions-item>
        <el-descriptions-item label="平台">{{ attempt.platform || '-' }}</el-descriptions-item>
        <el-descriptions-item label="店铺 ID">{{ attempt.store_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ attempt.status || '-' }}</el-descriptions-item>
        <el-descriptions-item label="错误码">{{ attempt.last_error_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="合同版本">{{ attempt.contract_version || '-' }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="oauth-message" />
      <el-alert v-if="callbackMessage" :title="callbackMessage" type="info" show-icon :closable="false" class="oauth-message" />
    </el-card>

    <el-card shadow="never">
      <template #header>授权生命周期占位</template>
      <el-form inline label-position="top">
        <el-form-item label="Store authorization ID">
          <el-input v-model="authorizationId" placeholder="仅填后端返回的 ID" />
        </el-form-item>
        <el-form-item label="Synthetic 场景">
          <el-select v-model="scenario" clearable placeholder="成功">
            <el-option label="托管失败" value="custody-fail" />
            <el-option label="429" value="rate-limit" />
            <el-option label="超时" value="timeout" />
          </el-select>
        </el-form-item>
        <el-form-item class="oauth-actions">
          <el-button :loading="actionLoading === 'refresh'" @click="runAction('refresh')">刷新引用</el-button>
          <el-button type="danger" :loading="actionLoading === 'revoke'" @click="runAction('revoke')">撤销授权</el-button>
          <el-button :loading="actionLoading === 'retry'" @click="runAction('retry')">失败重试</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import {
  fetchMarketplaceOAuthAttempt,
  initiateMarketplaceOAuth,
  refreshMarketplaceAuthorization,
  revokeMarketplaceAuthorization,
  retryMarketplaceAuthorization
} from '../../api/integrations';

const route = useRoute();
const form = reactive({ integration_config_id: '1', store_id: '1', platform: 'shopee', region: 'SG' });
const attempt = ref({});
const attemptId = ref('');
const authorizationId = ref('');
const scenario = ref('');
const loading = ref(false);
const actionLoading = ref('');
const errorMessage = ref('');
const callbackMessage = ref('');

const statusLabel = computed(() => attempt.value.status || '待发起');
const statusTagType = computed(() => ({
  succeeded: 'success', active: 'success', failed: 'danger', expired: 'danger', replayed: 'danger', forbidden: 'danger', offline: 'warning', pending: 'warning', initiated: 'warning'
}[attempt.value.status] || 'info'));

async function loadAttempt() {
  if (!attemptId.value) return;
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchMarketplaceOAuthAttempt(attemptId.value);
    if (!response.success) throw new Error(response.message || '授权状态查询失败');
    attempt.value = response.data || {};
  } catch (error) {
    errorMessage.value = error.message || '授权状态查询失败';
  } finally {
    loading.value = false;
  }
}

async function startAuthorization() {
  loading.value = true;
  errorMessage.value = '';
  callbackMessage.value = '';
  try {
    const response = await initiateMarketplaceOAuth({
      ...form,
      integration_config_id: Number(form.integration_config_id),
      store_id: Number(form.store_id),
      redirect_target_code: 'integrations'
    });
    if (!response.success) throw new Error(response.message || '授权发起失败');
    attempt.value = response.data || {};
    attemptId.value = response.data?.attempt_id || response.data?.id || '';
    if (response.data?.authorization_url) window.location.assign(response.data.authorization_url);
  } catch (error) {
    errorMessage.value = error.message || '授权发起失败';
  } finally {
    loading.value = false;
  }
}

async function runAction(action) {
  if (!authorizationId.value) {
    ElMessage.warning('请先填写后端返回的 Store authorization ID。');
    return;
  }
  actionLoading.value = action;
  errorMessage.value = '';
  try {
    const calls = {
      refresh: () => refreshMarketplaceAuthorization(authorizationId.value, scenario.value),
      revoke: () => revokeMarketplaceAuthorization(authorizationId.value, scenario.value),
      retry: () => retryMarketplaceAuthorization(authorizationId.value)
    };
    const response = await calls[action]();
    if (!response.success) throw new Error(response.message || `${action} 失败`);
    callbackMessage.value = `synthetic ${action} 已返回 ${response.data?.status || 'pending'}；未连接真实平台。`;
  } catch (error) {
    errorMessage.value = error.message || `${action} 失败`;
  } finally {
    actionLoading.value = '';
  }
}

onMounted(() => {
  const result = route.query.oauth_result;
  const queryAttemptId = route.query.attempt_id;
  if (typeof queryAttemptId === 'string') attemptId.value = queryAttemptId;
  if (typeof result === 'string') callbackMessage.value = `授权回调结果：${result}。请以服务端 attempt 状态为准。`;
  loadAttempt();
});
</script>

<style scoped>
.oauth-page { display: grid; gap: 16px; }
.oauth-header { display: flex; justify-content: space-between; gap: 16px; }
.oauth-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.oauth-message { margin-top: 16px; }
.oauth-actions { align-self: end; }
</style>
