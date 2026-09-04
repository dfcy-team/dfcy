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
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const formRef = ref();
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
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/';
  router.replace(redirect);
}
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

@media (max-width: 760px) {
  .login-page { grid-template-columns: 1fr; }
  .login-context { min-height: 260px; }
  .login-context h1 { font-size: 28px; }
  .login-context dl { display: none; }
}
</style>
