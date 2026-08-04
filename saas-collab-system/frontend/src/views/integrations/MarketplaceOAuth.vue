<template>
  <section class="oauth-page" aria-live="polite">
    <header class="oauth-header">
      <div>
        <h1 class="page-title">Marketplace authorization</h1>
        <p>Backend-provided authorization URLs only. Synthetic mode is active; no real platform request is sent.</p>
      </div>
      <el-tag :type="statusTagType">{{ statusLabel }}</el-tag>
    </header>

    <el-alert
      title="The page does not persist authorization URLs, state, callback query, code, tokens, or credentials."
      type="warning"
      show-icon
      :closable="false"
    />
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />
    <el-alert v-if="callbackMessage" :title="callbackMessage" type="info" show-icon :closable="false" />

    <el-card shadow="never" :aria-busy="loading">
      <template #header>Start authorization</template>
      <el-form :model="form" label-width="150px" @submit.prevent="startAuthorization">
        <el-form-item label="Platform">
          <el-select v-model="form.platform" style="width: 220px" :disabled="!canAuthorize">
            <el-option label="Shopee" value="shopee" />
            <el-option label="TikTok Shop" value="tiktok" />
          </el-select>
        </el-form-item>
        <el-form-item label="Integration config">
          <el-select v-model="form.integration_config_id" style="width: 320px" :disabled="!canAuthorize">
            <el-option v-for="config in configOptions" :key="config.id" :label="`${config.id} · ${config.account_alias || config.platform}`" :value="config.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Store">
          <el-select v-model="form.store_id" style="width: 320px" :disabled="!canAuthorize">
            <el-option v-for="store in storeOptions" :key="store.store_id" :label="`${store.store_id} · ${store.store_name || store.platform}`" :value="store.store_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Region"><el-input v-model="form.region" maxlength="8" :disabled="!canAuthorize" /></el-form-item>
        <el-form-item label="Redirect target"><el-input model-value="integrations" disabled /></el-form-item>
        <el-form-item>
          <el-button v-if="canAuthorize" type="primary" :loading="loading" :disabled="!form.store_id" @click="startAuthorization">Start authorization</el-button>
          <el-button :loading="loading" :disabled="!attemptId" @click="loadAttempt">Refresh status</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" :aria-busy="loading">
      <template #header>OAuth attempt</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="Attempt ID">{{ attemptId || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Platform">{{ attempt.platform || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Store ID">{{ attempt.store_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Status">{{ attempt.status || 'idle' }}</el-descriptions-item>
        <el-descriptions-item label="Error code">{{ attempt.last_error_code || callbackErrorCode || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Contract version">{{ attempt.contract_version || '-' }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-if="!loading && !attemptId" description="No OAuth attempt selected" />
    </el-card>

    <el-card shadow="never" :aria-busy="actionLoading !== ''">
      <template #header>Authorized stores</template>
      <el-form inline label-position="top">
        <el-form-item label="Store authorization">
          <el-select v-model="authorizationId" clearable placeholder="Select a server-scoped authorization" style="width: 360px">
            <el-option v-for="authorization in authorizations" :key="authorization.id" :label="`${authorization.id} · ${authorization.store_name || authorization.platform}`" :value="String(authorization.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="Synthetic scenario">
          <el-select v-model="scenario" clearable placeholder="Success" style="width: 180px">
            <el-option label="Custody failure" value="custody-fail" />
            <el-option label="429" value="rate-limit" />
            <el-option label="Timeout" value="timeout" />
          </el-select>
        </el-form-item>
        <el-form-item class="oauth-actions">
          <el-button v-if="canRotate" :disabled="!canRunAction('refresh')" :loading="actionLoading === 'refresh'" @click="runAction('refresh')">Refresh references</el-button>
          <el-button v-if="canRevoke" type="danger" :disabled="!canRunAction('revoke')" :loading="actionLoading === 'revoke'" @click="runAction('revoke')">Revoke authorization</el-button>
          <el-button v-if="canRetry" :disabled="!canRunAction('retry')" :loading="actionLoading === 'retry'" @click="runAction('retry')">Retry failed authorization</el-button>
        </el-form-item>
      </el-form>
      <el-empty v-if="!loading && authorizations.length === 0" description="No server-scoped authorizations are available" />
    </el-card>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { formatApiError } from '../../api/request';
import {
  fetchIntegrationConfigs,
  fetchMarketplaceOAuthAttempt,
  fetchMarketplaceStoreAuthorizations,
  initiateMarketplaceOAuth,
  refreshMarketplaceAuthorization,
  revokeMarketplaceAuthorization,
  retryMarketplaceAuthorization
} from '../../api/integrations';

const route = useRoute();
const auth = useAuthStore();
const form = reactive({ integration_config_id: '', store_id: '', platform: 'shopee', region: 'SG' });
const attempt = ref({});
const attemptId = ref('');
const authorizationId = ref('');
const authorizations = ref([]);
const configOptions = ref([]);
const scenario = ref('');
const loading = ref(false);
const actionLoading = ref('');
const errorMessage = ref('');
const callbackMessage = ref('');
const callbackErrorCode = ref('');
let pollTimer;

const canAuthorize = computed(() => auth.hasPermission('integrations.store.authorize'));
const canRotate = computed(() => auth.hasPermission('integrations.credential.rotate'));
const canRevoke = computed(() => auth.hasPermission('integrations.store.revoke'));
const canRetry = computed(() => auth.hasPermission('integrations.store.retry'));
const selectedAuthorization = computed(() => authorizations.value.find((item) => String(item.id) === String(authorizationId.value)) || null);
const statusLabel = computed(() => attempt.value.status || 'idle');
const statusTagType = computed(() => ({
  succeeded: 'success', active: 'success', failed: 'danger', expired: 'danger', replayed: 'danger', forbidden: 'danger', offline: 'warning', pending: 'warning', initiated: 'warning', callback_received: 'warning'
}[attempt.value.status] || 'info'));
const storeOptions = computed(() => authorizations.value.filter((item) => item.platform === form.platform));

function showError(response, fallback) {
  errorMessage.value = response?.http_status ? formatApiError(response) : (response?.message || fallback);
}

function canRunAction(action) {
  const selected = selectedAuthorization.value;
  if (!selected) return false;
  if (action === 'refresh' || action === 'revoke') return ['active', 'pending'].includes(selected.status);
  return ['error', 'reconcile_required'].includes(selected.status);
}

async function loadReferenceData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const [configResponse, authorizationResponse] = await Promise.all([
      fetchIntegrationConfigs(),
      fetchMarketplaceStoreAuthorizations()
    ]);
    if (!configResponse.success) throw configResponse;
    if (!authorizationResponse.success) throw authorizationResponse;
    configOptions.value = Array.isArray(configResponse.data?.results) ? configResponse.data.results : (configResponse.data?.items || []);
    authorizations.value = Array.isArray(authorizationResponse.data?.results) ? authorizationResponse.data.results : (authorizationResponse.data?.items || []);
    const firstConfig = configOptions.value.find((config) => config.platform === form.platform);
    const firstStore = storeOptions.value[0];
    form.integration_config_id ||= firstConfig?.id || '';
    form.store_id ||= firstStore?.store_id || '';
    if (!authorizationId.value && authorizations.value[0]) authorizationId.value = String(authorizations.value[0].id);
  } catch (error) {
    showError(error, 'Unable to load server-scoped authorization data.');
  } finally {
    loading.value = false;
  }
}

async function loadAttempt({ silent = false } = {}) {
  if (!attemptId.value) return;
  if (!silent) loading.value = true;
  errorMessage.value = '';
  try {
    const response = await fetchMarketplaceOAuthAttempt(attemptId.value);
    if (!response.success) throw response;
    attempt.value = response.data || {};
    if (['initiated', 'callback_received', 'pending'].includes(attempt.value.status)) startPolling();
    else stopPolling();
  } catch (error) {
    stopPolling();
    showError(error, 'Unable to load OAuth attempt status.');
    if (!error?.http_status) attempt.value = { ...attempt.value, status: 'offline' };
  } finally {
    if (!silent) loading.value = false;
  }
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = window.setInterval(() => loadAttempt({ silent: true }), 2000);
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = undefined;
}

async function startAuthorization() {
  if (!canAuthorize.value) return;
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
    if (!response.success) throw response;
    attempt.value = response.data || {};
    attemptId.value = response.data?.attempt_id || response.data?.id || '';
    startPolling();
    if (response.data?.authorization_url) window.location.assign(response.data.authorization_url);
  } catch (error) {
    showError(error, 'Unable to start authorization.');
  } finally {
    loading.value = false;
  }
}

async function runAction(action) {
  if (!selectedAuthorization.value || !canRunAction(action)) return;
  actionLoading.value = action;
  errorMessage.value = '';
  try {
    const id = authorizationId.value;
    const calls = {
      refresh: () => refreshMarketplaceAuthorization(id, scenario.value),
      revoke: () => revokeMarketplaceAuthorization(id, scenario.value),
      retry: () => retryMarketplaceAuthorization(id)
    };
    const response = await calls[action]();
    if (!response.success) throw response;
    callbackMessage.value = `Synthetic ${action} completed with status ${response.data?.status || 'pending'}.`;
    await loadReferenceData();
    if (response.data?.attempt_id) {
      attemptId.value = String(response.data.attempt_id);
      await loadAttempt();
    }
  } catch (error) {
    showError(error, `Unable to complete ${action}.`);
  } finally {
    actionLoading.value = '';
  }
}

onMounted(async () => {
  const result = route.query.oauth_result;
  const queryAttemptId = route.query.attempt_id;
  const queryErrorCode = route.query.error_code;
  if (typeof queryAttemptId === 'string') attemptId.value = queryAttemptId;
  if (typeof result === 'string' && ['success', 'failed'].includes(result)) callbackMessage.value = `OAuth callback result: ${result}.`;
  if (typeof queryErrorCode === 'string' && /^[A-Z][A-Z0-9_]{2,79}$/.test(queryErrorCode)) callbackErrorCode.value = queryErrorCode;
  await loadReferenceData();
  await loadAttempt();
});

onBeforeUnmount(stopPolling);
</script>

<style scoped>
.oauth-page { display: grid; gap: 16px; }
.oauth-header { display: flex; justify-content: space-between; gap: 16px; }
.oauth-header p { margin: -8px 0 0; color: #64748b; font-size: 13px; }
.oauth-actions { align-self: end; }
</style>
