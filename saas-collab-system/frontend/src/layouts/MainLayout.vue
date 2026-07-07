<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { menuRoutes } from '../router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const authStore = useAuthStore()

const currentTitle = computed(() => route.meta.title || '首页')
const currentUser = computed(() => authStore.currentUser)
const username = computed(() => currentUser.value?.username || '未登录用户')
const userRole = computed(() => currentUser.value?.roles?.[0] || '权限占位')
</script>

<template>
  <el-container class="main-layout">
    <el-aside class="main-sidebar" width="220px">
      <div class="brand">SaaS 协同系统</div>
      <el-menu
        class="side-menu"
        router
        :default-active="route.path"
        background-color="#111827"
        text-color="#cbd5e1"
        active-text-color="#ffffff"
      >
        <el-menu-item
          v-for="item in menuRoutes"
          :key="item.path"
          :index="item.path"
        >
          <span>{{ item.meta.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="main-panel">
      <el-header class="top-bar">
        <div>
          <h1>{{ currentTitle }}</h1>
          <p>菜单权限为前端显示占位，真实权限以后以后端 roles 和 permissions 为准。</p>
        </div>
        <div class="user-box">
          <el-avatar :size="32">{{ username.slice(0, 1).toUpperCase() }}</el-avatar>
          <div>
            <strong>{{ username }}</strong>
            <span>{{ userRole }}</span>
          </div>
        </div>
      </el-header>

      <el-main class="content-area">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
