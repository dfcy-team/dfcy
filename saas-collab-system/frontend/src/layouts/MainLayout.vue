<template>
  <el-container class="app-shell">
    <el-aside width="248px" class="app-sidebar desktop-sidebar">
      <div class="brand">
        <strong>SaaS 协同系统</strong>
        <span>{{ environmentLabel }}</span>
      </div>
      <AppMenu :items="visibleMenuItems" />
    </el-aside>

    <el-container class="app-workspace">
      <el-header class="app-header">
        <div class="header-context">
          <el-button class="mobile-menu-button" text aria-label="打开导航菜单" @click="mobileMenuOpen = true">
            ☰
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>工作台</el-breadcrumb-item>
            <el-breadcrumb-item v-if="currentLabel && $route.path !== '/'">{{ currentLabel }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-user">
          <el-tag :type="useMock ? 'warning' : 'success'" effect="plain">{{ environmentLabel }}</el-tag>
          <div class="header-user__identity">
            <strong>{{ auth.currentUser?.username }}</strong>
            <span>租户 {{ auth.currentUser?.tenant_id }} · {{ roleLabel }}</span>
          </div>
          <el-button text @click="handleLogout">退出</el-button>
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <el-drawer v-model="mobileMenuOpen" direction="ltr" size="288px" :with-header="false">
      <div class="brand">
        <strong>SaaS 协同系统</strong>
        <span>{{ environmentLabel }}</span>
      </div>
      <AppMenu :items="visibleMenuItems" @select="mobileMenuOpen = false" />
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, defineComponent, h, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMenu, ElMenuItem, ElSubMenu } from 'element-plus';
import 'element-plus/theme-chalk/el-container.css';
import 'element-plus/theme-chalk/el-aside.css';
import 'element-plus/theme-chalk/el-header.css';
import 'element-plus/theme-chalk/el-main.css';
import 'element-plus/theme-chalk/el-menu.css';
import 'element-plus/theme-chalk/el-menu-item.css';
import 'element-plus/theme-chalk/el-sub-menu.css';
import 'element-plus/theme-chalk/el-drawer.css';
import 'element-plus/theme-chalk/el-breadcrumb.css';
import 'element-plus/theme-chalk/el-tag.css';
import 'element-plus/theme-chalk/el-button.css';
import { useAuthStore } from '../stores/auth';
import { useMock } from '../api/request';
import { filterMenuItems, findMenuLabel } from '../router/menu';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const mobileMenuOpen = ref(false);

const visibleMenuItems = computed(() => filterMenuItems(auth.currentUser));
const currentLabel = computed(() => findMenuLabel(route.path, visibleMenuItems.value));
const environmentLabel = computed(() => (useMock ? 'Mock' : 'Pilot API'));
const roleLabel = computed(() => {
  if (auth.currentUser?.is_superuser) return '超级管理员';
  return auth.currentUser?.roles?.join(' / ') || auth.currentUser?.user_type || '用户';
});

function handleLogout() {
  auth.logout();
  router.replace('/login');
}

const AppMenu = defineComponent({
  props: { items: { type: Array, required: true } },
  emits: ['select'],
  setup(props, { emit }) {
    const renderItem = (item) => {
      if (item.children) {
        return h(
          ElSubMenu,
          { index: item.label },
          {
            title: () => item.label,
            default: () => item.children.map(renderItem)
          }
        );
      }
      return h(ElMenuItem, { index: item.path, onClick: () => emit('select') }, () => item.label);
    };
    return () => h(ElMenu, { router: true, defaultActive: route.path, class: 'menu' }, () => props.items.map(renderItem));
  }
});
</script>

<style scoped>
.app-shell { min-height: 100vh; }
.app-workspace { min-width: 0; }

.app-sidebar {
  border-right: 1px solid #d9e2ec;
  background: #fff;
}

.brand {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 64px;
  padding: 0 20px;
  border-bottom: 1px solid #d9e2ec;
}

.brand strong { color: #172033; font-size: 16px; }
.brand span { margin-top: 3px; color: #718096; font-size: 11px; }
.menu { border-right: 0; }

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 20px;
  border-bottom: 1px solid #d9e2ec;
  background: #fff;
}

.header-context,
.header-user {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-user__identity {
  display: flex;
  flex-direction: column;
  min-width: 132px;
}

.header-user__identity strong { color: #172033; font-size: 13px; }
.header-user__identity span { color: #718096; font-size: 11px; }
.mobile-menu-button { display: none; width: 36px; min-width: 36px; padding: 0; font-size: 20px; }
.app-main { min-width: 0; padding: 20px; overflow-x: auto; }

@media (max-width: 900px) {
  .desktop-sidebar { display: none; }
  .mobile-menu-button { display: inline-flex; }
  .app-header { padding: 0 12px; }
  .app-main { width: 100%; padding: 14px; }
  .header-user .el-tag,
  .header-user__identity span { display: none; }
  .header-user__identity { min-width: 0; }
}
</style>
