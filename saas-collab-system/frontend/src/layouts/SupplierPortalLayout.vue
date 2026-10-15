<template>
  <div class="portal">
    <header><div><strong>供应商协同</strong><small>{{ auth.currentUser?.supplier_name }} · {{ auth.currentUser?.full_name || auth.currentUser?.username }}</small></div>
      <nav><router-link to="/supplier/orders">采购订单</router-link><router-link to="/supplier/shipments">我的发货单</router-link><el-button text @click="logout">退出登录</el-button></nav>
    </header>
    <router-view />
  </div>
</template>
<script setup>
import { useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { onAuthenticationExpired } from '../api/request';
const auth = useAuthStore(), router = useRouter();
function logout() { auth.logout(); router.replace('/supplier/login'); }
onAuthenticationExpired(logout);
</script>
<style scoped>
.portal { min-height:100vh; background:#f4f6fa; } header { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:18px 24px; background:white; border-bottom:1px solid #e5e7eb; } small { display:block; color:#667085; margin-top:6px; } nav { display:flex; align-items:center; gap:20px; } a { text-decoration:none; color:#475467; } .router-link-active { color:#2563eb; } @media(max-width:640px){header{align-items:flex-start;flex-direction:column;padding:16px;}nav{gap:14px;}}
</style>
