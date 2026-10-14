<template>
  <section class="binding-panel" aria-labelledby="feishu-binding-title">
    <h3 id="feishu-binding-title">飞书账号绑定</h3>
    <el-skeleton v-if="loadingStatus" :rows="3" animated aria-label="正在加载飞书绑定状态" />
    <el-alert v-else-if="useMock" title="当前演示模式不支持飞书绑定。" type="info" :closable="false" show-icon />
    <template v-else-if="status?.bound">
      <el-alert
        :title="status.status === 'active' ? '已绑定飞书账号，可使用飞书扫码登录。' : '已绑定飞书账号，但当前已停用，不能用于飞书扫码登录。请联系管理员处理。'"
        :type="status.status === 'active' ? 'success' : 'warning'"
        :closable="false"
        show-icon
      />
      <p class="binding-copy">账号：{{ status.username || '已绑定账号' }}</p>
      <p v-if="status.bound_at" class="binding-copy">绑定时间：{{ formatDate(status.bound_at) }}</p>
      <p class="binding-help">如需更换绑定的飞书账号，请联系管理员处理。</p>
    </template>
    <el-alert v-else-if="status?.enabled === false" title="飞书绑定暂不可用，请稍后重试或联系管理员。" type="info" :closable="false" show-icon />
    <el-alert v-else-if="!statusLoaded" title="无法确认飞书绑定状态，请稍后重试。" type="warning" :closable="false" show-icon />
    <template v-else>
      <p class="binding-copy">首次绑定需验证当前系统密码；绑定后可直接飞书扫码登录。</p>
      <el-form label-position="top" @submit.prevent="startBinding">
        <el-form-item label="当前系统密码" required>
          <el-input
            v-model="currentPassword"
            type="password"
            autocomplete="current-password"
            placeholder="请输入当前系统密码"
            show-password
            :disabled="starting || completing || !statusLoaded || status?.enabled !== true"
            @keyup.enter="startBinding"
          />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="starting" :disabled="completing || starting || !statusLoaded || status?.enabled !== true">验证并生成二维码</el-button>
      </el-form>
      <p v-if="qrState === 'ready'" class="binding-help" role="status">请使用您要绑定的飞书账号扫描二维码。</p>
      <p v-else-if="qrState === 'expired'" class="binding-error" role="alert">二维码已过期，请重新验证密码并生成二维码。</p>
      <p v-else-if="qrState === 'config_unavailable'" class="binding-error" role="alert">飞书扫码暂时不可用，请稍后重试。</p>
      <div v-if="qrState === 'ready'" ref="qrContainer" class="binding-qr" aria-label="飞书绑定二维码" />
    </template>
    <el-alert v-if="message" class="binding-message" :title="message" type="error" :closable="false" show-icon />
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue';
import { completeFeishuBinding, getFeishuBindingStatus, startFeishuBinding } from '../api/auth';
import { useMock } from '../api/request';
import { mountFeishuQr } from '../utils/feishuQrLogin';

const props = defineProps({ active: { type: Boolean, default: false }, callbackMarker: { type: String, default: '' }, callbackError: { type: String, default: '' } });
const emit = defineEmits(['callback-consumed']);
const status = ref(null);
const statusLoaded = ref(false);
const loadingStatus = ref(false);
const starting = ref(false);
const completing = ref(false);
const currentPassword = ref('');
const message = ref('');
const qrState = ref('idle');
const qrContainer = ref(null);
let requestGeneration = 0;
let removeQr = null;
let consumedCallback = '';
const messages = {
  config_unavailable: '飞书绑定暂不可用，请稍后重试。',
  retry_required: '绑定暂未完成，请稍后重新验证密码并扫码。',
  state_invalid: '绑定请求已失效，请重新生成二维码。',
  expired: '二维码已过期，请重新生成。',
  denied: '您已取消飞书授权，可重新生成二维码。',
  provider_error: '飞书授权暂时失败，请稍后重试。',
  account_unavailable: '当前系统账号不可用，请联系管理员。',
  password_invalid: '当前系统密码不正确，请重新输入。',
  already_bound: '此账号已绑定飞书，如需更换请联系管理员。',
  identity_in_use: '该飞书账号已绑定其他系统账号，请使用其他飞书账号。',
};

function showError(code, fallback = '飞书绑定失败，请稍后重试。') {
  message.value = messages[code] || fallback;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function stopQr() {
  removeQr?.();
  removeQr = null;
  if (qrContainer.value) qrContainer.value.replaceChildren();
}

async function refreshStatus(generation = requestGeneration) {
  loadingStatus.value = true;
  statusLoaded.value = false;
  try {
    const response = await getFeishuBindingStatus();
    if (generation !== requestGeneration || !props.active) return;
    if (!response?.success) {
      showError(response?.code);
      return;
    }
    status.value = response.data || null;
    statusLoaded.value = Boolean(response.data && typeof response.data.enabled === 'boolean');
    if (!statusLoaded.value) showError('', '无法确认飞书绑定状态，请稍后重试。');
  } catch {
    if (generation === requestGeneration && props.active) showError('', '无法确认飞书绑定状态，请稍后重试。');
  } finally {
    if (generation === requestGeneration) loadingStatus.value = false;
  }
}

async function finishBinding(marker) {
  if (!marker || consumedCallback === marker || useMock) return;
  consumedCallback = marker;
  const generation = requestGeneration;
  completing.value = true;
  message.value = '';
  try {
    const response = await completeFeishuBinding();
    if (generation !== requestGeneration || !props.active) return;
    if (!response?.success) {
      showError(response?.code);
      if (response?.code === 'already_bound') {
        await refreshStatus(generation);
        if (generation === requestGeneration && props.active) showError('already_bound');
      }
      return;
    }
    status.value = response.data || null;
    statusLoaded.value = Boolean(response.data && typeof response.data.enabled === 'boolean');
    qrState.value = 'idle';
  } finally {
    if (generation === requestGeneration) completing.value = false;
    emit('callback-consumed', marker);
  }
}

async function startBinding() {
  if (starting.value || completing.value || !props.active || !statusLoaded.value || status.value?.enabled !== true || status.value?.bound) return;
  if (!currentPassword.value) {
    message.value = '请输入当前系统密码。';
    return;
  }
  stopQr();
  qrState.value = 'idle';
  message.value = '';
  starting.value = true;
  const generation = requestGeneration;
  const password = currentPassword.value;
  let response;
  try {
    try {
      response = await startFeishuBinding(password);
    } finally {
      if (generation === requestGeneration) currentPassword.value = '';
    }
    if (generation !== requestGeneration || !props.active) return;
    if (!response?.success) {
      showError(response?.code);
      return;
    }
    qrState.value = 'ready';
    await new Promise((resolve) => requestAnimationFrame(resolve));
    if (generation !== requestGeneration || !props.active || !qrContainer.value) return;
    qrContainer.value.id = 'feishu-binding-qr';
    const cleanup = await mountFeishuQr({
      id: 'feishu-binding-qr',
      container: qrContainer.value,
      authorizeUrl: response.data?.authorize_url,
      isActive: () => props.active && generation === requestGeneration && qrState.value === 'ready',
      onError: (code) => {
        if (generation !== requestGeneration || !props.active) return;
        qrState.value = code === 'expired' ? 'expired' : 'config_unavailable';
        if (qrContainer.value) qrContainer.value.replaceChildren();
      },
    });
    if (generation !== requestGeneration || !props.active) cleanup?.();
    else removeQr = cleanup;
  } finally {
    if (generation === requestGeneration) starting.value = false;
  }
}

watch(() => [props.active, props.callbackMarker], async ([active, marker]) => {
  if (!active) {
    requestGeneration += 1;
    currentPassword.value = '';
    loadingStatus.value = false;
    starting.value = false;
    completing.value = false;
    status.value = null;
    statusLoaded.value = false;
    message.value = '';
    stopQr();
    qrState.value = 'idle';
    return;
  }
  const generation = ++requestGeneration;
  loadingStatus.value = false;
  starting.value = false;
  completing.value = false;
  message.value = '';
  status.value = null;
  await refreshStatus(generation);
  if (props.callbackError) showError(props.callbackError);
  if (generation === requestGeneration && marker) await finishBinding(marker);
}, { immediate: true });

onBeforeUnmount(() => {
  requestGeneration += 1;
  stopQr();
});
</script>

<style scoped>
.binding-panel { min-width: 0; padding: 4px 2px 12px; }
.binding-panel h3 { margin: 4px 0 12px; color: #1f2937; font-size: 16px; }
.binding-copy, .binding-help { color: #64748b; font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.binding-help { margin: 12px 0 0; }
.binding-error { color: #b42318; font-size: 13px; line-height: 1.6; }
.binding-message { margin-top: 14px; }
.binding-qr { width: 240px; height: 240px; max-width: 100%; margin: 16px auto 0; overflow: hidden; }
.binding-qr :deep(iframe) { width: 300px !important; height: 300px !important; border: 0; transform: scale(.8); transform-origin: top left; }
</style>
