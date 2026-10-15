<template>
  <main class="supplier-login">
    <el-card class="login-card">
      <h1>供应商协同登录</h1>
      <p>查看采购单、登记分批发货并上传箱号附件。账号由采购联系人提供。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <el-form @submit.prevent="submit" label-position="top">
        <el-form-item label="供应商账号"><el-input v-model="form.username" autocomplete="username" aria-label="供应商账号" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password autocomplete="current-password" aria-label="供应商密码" /></el-form-item>
        <el-button native-type="submit" type="primary" :loading="auth.loading">登录供应商协同</el-button>
      </el-form>
      <router-link to="/login">采购人员进入协同系统</router-link>
    </el-card>
  </main>
</template>
<script setup>
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { supplierRedirect } from '../../utils/supplierPortal';
const auth = useAuthStore(), route = useRoute(), router = useRouter();
const form = reactive({ username: '', password: '' }), error = ref('');
async function submit() {
  if (auth.loading) return;
  if (!form.username.trim() || !form.password) { error.value = '请填写账号和密码。'; return; }
  const response = await auth.loginSupplier(form);
  form.password = '';
  if (!response.success) { error.value = '账号、密码或供应商绑定无效，请联系采购核查。'; return; }
  await router.replace(supplierRedirect(route.query.redirect));
}
</script>
<style scoped>
.supplier-login { min-height:100vh; display:grid; place-items:center; background:#f2f5f9; padding:20px; box-sizing:border-box; }
.login-card { width:min(440px,100%); } h1 { font-size:24px; } p { line-height:1.7; color:#667085; }
.el-form { margin:24px 0; } .el-button { width:100%; } a { font-size:14px; }
</style>
