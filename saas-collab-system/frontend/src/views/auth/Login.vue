<template>
  <main class="login-page">
    <section class="login-context" aria-label="系统登录说明">
      <div class="login-context__brand">鼎峰创域科技</div>
      <h1>跨境业务协同工作台</h1>
      <p>连接运营、采购、供应链、财务与管理团队，让业务协作更高效。</p>
      <dl>
        <div><dt>统一入口</dt><dd>集中处理各项日常业务</dd></div>
        <div><dt>高效协同</dt><dd>跨团队共享进度与业务信息</dd></div>
        <div><dt>岗位权限</dt><dd>只展示您可使用的功能和数据</dd></div>
      </dl>
    </section>

    <section class="login-panel">
      <div>
        <span class="login-panel__eyebrow">账号登录</span>
        <h2>欢迎回来</h2>
        <p>请使用企业为您分配的账号登录。</p>
      </div>

      <section v-if="feishuEnabled" class="feishu-login" aria-label="飞书扫码登录">
        <h3>飞书扫码登录</h3>
        <div v-show="!qrError" id="feishu-qr-login" ref="qrContainer" class="feishu-qr" />
        <el-alert v-if="qrError" :title="qrError" type="warning" :closable="false" show-icon />
        <el-button v-if="qrError || qrExpired" text type="primary" :loading="qrLoading" @click="refreshQr">刷新二维码</el-button>
        <p v-if="!qrError">使用飞书扫描二维码登录</p>
      </section>
      <el-alert v-if="configError || (!feishuEnabled && qrError)" :title="configError || qrError" type="warning" :closable="false" show-icon />

      <el-alert
        v-if="auth.errorMessage"
        :title="auth.errorMessage"
        type="error"
        :closable="false"
        show-icon
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
        <el-form-item label="用户名" prop="username">
          <el-input v-model.trim="form.username" autocomplete="username" autofocus placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button class="login-submit" type="primary" native-type="submit" :loading="auth.loading">
          进入工作台
        </el-button>
      </el-form>

      <p class="login-panel__boundary">首次登录、忘记密码或账号无法使用时，请联系企业管理员。</p>
    </section>
  </main>
</template>

<script setup>
import { onMounted, onBeforeUnmount, nextTick, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';
import { safeLocalRedirect } from '../../utils/ssoRedirect';
import { getFeishuLoginConfig, startFeishuLogin } from '../../api/auth';
import { feishuErrorMessages, mountFeishuQr, validateAuthorizeUrl } from '../../utils/feishuQrLogin';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const formRef = ref();
const qrContainer = ref();
const feishuEnabled = ref(false);
const qrError = ref('');
const qrExpired = ref(false);
const qrLoading = ref(false);
const configError = ref('');
let stopQr = null;
let qrSequence = 0;
let disposed = false;
const form = reactive({ username: '', password: '' });
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
};

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  const response = await auth.login(form);
  if (!response.success) {
    auth.errorMessage = response.http_status === 401 ? '用户名或密码错误。' : response.message;
    return;
  }
  ElMessage.success('登录成功');
  const redirect = safeLocalRedirect(route.query.redirect);
  router.replace(redirect);
}

async function refreshQr() {
  if (qrLoading.value || disposed) return;
  qrLoading.value = true;
  const sequence = ++qrSequence;
  stopQr?.();
  qrError.value = '';
  qrExpired.value = false;
  try {
    await nextTick();
    if (qrContainer.value) qrContainer.value.replaceChildren();
    const started = await startFeishuLogin();
    if (disposed || sequence !== qrSequence) return;
    const authorizeUrl = validateAuthorizeUrl(started?.data?.authorize_url);
    if (!started?.success || !authorizeUrl) {
      qrError.value = feishuErrorMessages[started?.code] || feishuErrorMessages.provider_error;
      return;
    }
    await nextTick();
    if (disposed || sequence !== qrSequence || !qrContainer.value) return;
    stopQr = await mountFeishuQr({ id: 'feishu-qr-login', container: qrContainer.value, authorizeUrl: authorizeUrl.toString(), isActive: () => !disposed && sequence === qrSequence, onError: (code) => {
      qrExpired.value = code === 'expired';
      qrError.value = feishuErrorMessages[code] || feishuErrorMessages.config_unavailable;
    } });
  } finally {
    if (sequence === qrSequence) qrLoading.value = false;
  }
}

onMounted(async () => {
  const query = route.query;
  if (query.feishu || query.feishu_error) {
    const redirectAfterLogin = query.redirect;
    const error = typeof query.feishu_error === 'string' ? query.feishu_error : '';
    const cleanQuery = { ...query };
    delete cleanQuery.feishu;
    delete cleanQuery.feishu_error;
    await router.replace({ path: '/login', query: cleanQuery });
    if (error) {
      qrError.value = feishuErrorMessages[error] || feishuErrorMessages.provider_error;
    } else {
      const result = await auth.completeFeishuLogin();
      if (result.success) {
        await router.replace(safeLocalRedirect(redirectAfterLogin));
        return;
      }
      configError.value = feishuErrorMessages[result.code] || feishuErrorMessages.provider_error;
    }
  }
  if (disposed) return;
  const config = await getFeishuLoginConfig();
  if (disposed) return;
  feishuEnabled.value = Boolean(config?.success && config.data?.enabled === true);
  if (!config?.success) configError.value = feishuErrorMessages[config?.code] || feishuErrorMessages.config_unavailable;
  if (feishuEnabled.value && !query.feishu && !query.feishu_error) await refreshQr();
});
onBeforeUnmount(() => { disposed = true; qrSequence += 1; stopQr?.(); });
</script>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(360px, 1.1fr);
  min-height: 100vh;
  background: #f4f7fb;
}

.login-context,
.login-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: clamp(32px, 7vw, 96px);
}

.login-context {
  color: #f8fafc;
  background: #17324d;
}

.login-context__brand,
.login-panel__eyebrow {
  font-size: 12px;
  font-weight: 700;
}

.login-context h1 {
  max-width: 520px;
  margin: 24px 0 12px;
  font-size: 38px;
  letter-spacing: 0;
}

.login-context p {
  max-width: 520px;
  color: #d9e6f2;
  line-height: 1.7;
}

.login-context dl {
  display: grid;
  gap: 12px;
  margin: 48px 0 0;
}

.login-context dl div {
  display: flex;
  justify-content: space-between;
  max-width: 420px;
  padding-bottom: 10px;
  border-bottom: 1px solid #496078;
}

.login-context dt { color: #a9bfd3; }
.login-context dd { margin: 0; }

.login-panel {
  width: min(100%, 620px);
}

.login-panel h2 {
  margin: 8px 0;
  color: #172033;
  font-size: 30px;
}

.login-panel > div > p,
.login-panel__boundary {
  color: #64748b;
}

.login-panel :deep(.el-alert) { margin: 20px 0; }
.login-panel :deep(.el-form) { margin-top: 24px; }
.login-submit { width: 100%; min-height: 42px; }
.login-panel__boundary { margin-top: 22px; font-size: 12px; line-height: 1.6; }
.feishu-login { margin-top: 20px; padding: 18px; text-align: center; border: 1px solid #dbe3ec; border-radius: 8px; background: #fff; }
.feishu-login h3 { margin: 0 0 12px; font-size: 16px; color: #172033; }
.feishu-login p { margin: 8px 0 0; color: #64748b; font-size: 13px; }
.feishu-qr { width: 300px; min-width: 300px; min-height: 300px; margin: 0 auto; }

@media (max-width: 760px) {
  .login-page { grid-template-columns: 1fr; }
  .login-context { min-height: 260px; }
  .login-context h1 { font-size: 28px; }
  .login-context dl { display: none; }
}
</style>
