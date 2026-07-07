<script setup>
import { reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const form = reactive({
  username: 'demo_admin',
  password: 'mock_password',
})

function handleLogin() {
  authStore.mockLogin()
  router.push('/dashboard')
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-copy">
        <h1>SaaS 协同系统</h1>
        <p>当前登录仅使用前端 mock 用户，不请求真实后端接口。</p>
      </div>

      <el-card class="login-card" shadow="never">
        <h2>登录</h2>
        <el-form label-position="top" @submit.prevent>
          <el-form-item label="用户名">
            <el-input v-model="form.username" disabled />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" type="password" disabled show-password />
          </el-form-item>
          <el-button class="login-button" type="primary" @click="handleLogin">
            使用 mock 用户登录
          </el-button>
        </el-form>
      </el-card>
    </section>
  </main>
</template>
