<template>
  <main class="login-page">
    <section class="login-panel">
      <h1>阶段0登录占位</h1>
      <p>当前使用 Mock 用户状态，真实权限以后端 /api/internal/auth/me/ 返回为准。</p>
      <el-button type="primary" @click="handleMockLogin">Mock 登录</el-button>
    </section>
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();
const router = useRouter();

function handleMockLogin() {
  auth.loginWithMock();
  router.push('/');
}
</script>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
}

.login-panel {
  width: min(420px, calc(100vw - 32px));
  padding: 24px;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #fff;
}
</style>
