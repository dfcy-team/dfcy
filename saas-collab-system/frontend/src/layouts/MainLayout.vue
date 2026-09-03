<template>
  <el-container class="app-shell">
    <el-aside width="248px" class="app-sidebar desktop-sidebar">
      <div class="navigation-surface">
        <div class="brand">
          <strong>鼎峰创域科技</strong>
        </div>
        <AppMenu :items="visibleMenuItems" />
      </div>
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
          <div class="header-user__identity">
            <strong :title="auth.currentUser?.username">{{ auth.currentUser?.username }}</strong>
            <span>{{ roleLabel }}</span>
          </div>
          <el-button text @click="handleLogout">退出登录</el-button>
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <el-drawer
      v-model="mobileMenuOpen"
      class="navigation-drawer"
      direction="ltr"
      size="288px"
      :with-header="false"
    >
      <div class="navigation-surface">
        <div class="brand">
          <strong>鼎峰创域科技</strong>
        </div>
        <AppMenu :items="visibleMenuItems" @select="mobileMenuOpen = false" />
      </div>
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
import 'element-plus/theme-chalk/el-button.css';
import { useAuthStore } from '../stores/auth';
import { filterMenuItems, findMenuLabel } from '../router/menu';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const mobileMenuOpen = ref(false);

const visibleMenuItems = computed(() => filterMenuItems(auth.currentUser));
const currentLabel = computed(() => findMenuLabel(route.path, visibleMenuItems.value));
const roleLabel = computed(() => {
  const roles = auth.currentUser?.roles?.filter(Boolean) || [];
  return roles.length ? roles.join(' / ') : '未分配角色';
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
  border-right: 1px solid #263449;
  background: #101827;
}

.navigation-surface {
  min-height: 100%;
  color: #cbd5e1;
  background: #101827;
}

.brand {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 64px;
  padding: 0 20px;
  border-bottom: 1px solid #263449;
  background: #0b1220;
}

.brand strong { color: #f8fafc; font-size: 16px; }

:global(.navigation-drawer) {
  --el-drawer-bg-color: #101827;
  background: #101827;
}

:global(.navigation-drawer .el-drawer__body) {
  padding: 0;
  background: #101827;
}

:deep(.navigation-surface .menu) {
  --el-menu-active-color: #ffffff;
  --el-menu-bg-color: #101827;
  --el-menu-border-color: transparent;
  --el-menu-hover-bg-color: #1e293b;
  --el-menu-hover-text-color: #f8fafc;
  --el-menu-item-height: 46px;
  --el-menu-sub-item-height: 42px;
  border-right: 0;
  background: #101827;
}

:deep(.navigation-surface .menu .el-menu-item),
:deep(.navigation-surface .menu .el-sub-menu__title) {
  color: #cbd5e1;
}

:deep(.navigation-surface .menu .el-menu-item:hover),
:deep(.navigation-surface .menu .el-menu-item:focus),
:deep(.navigation-surface .menu .el-sub-menu__title:hover),
:deep(.navigation-surface .menu .el-sub-menu__title:focus) {
  color: #f8fafc;
  background: #1e293b;
}

:deep(.navigation-surface .menu .el-menu-item.is-active),
:deep(.navigation-surface .menu .el-menu-item.is-active:hover),
:deep(.navigation-surface .menu .el-menu-item.is-active:focus) {
  color: #ffffff;
  font-weight: 600;
  background: #1d4ed8;
}

:deep(.navigation-surface .menu .el-sub-menu.is-opened > .el-sub-menu__title),
:deep(.navigation-surface .menu .el-sub-menu.is-active > .el-sub-menu__title) {
  color: #f8fafc;
  background: #172235;
}

:deep(.navigation-surface .menu .el-sub-menu .el-menu) {
  background: #0b1220;
}

:deep(.navigation-surface .menu .el-sub-menu .el-menu-item) {
  color: #b7c5d6;
}

:deep(.navigation-surface .menu .el-sub-menu .el-menu-item:hover),
:deep(.navigation-surface .menu .el-sub-menu .el-menu-item:focus) {
  color: #f8fafc;
  background: #1e293b;
}

:deep(.navigation-surface .menu .el-sub-menu .el-menu-item.is-active),
:deep(.navigation-surface .menu .el-sub-menu .el-menu-item.is-active:hover),
:deep(.navigation-surface .menu .el-sub-menu .el-menu-item.is-active:focus) {
  color: #ffffff;
  background: #1e40af;
}

:deep(.navigation-surface .menu .el-sub-menu__icon-arrow) {
  color: #94a3b8;
}

:deep(.navigation-surface .menu .el-sub-menu__title:hover .el-sub-menu__icon-arrow),
:deep(.navigation-surface .menu .el-sub-menu.is-opened > .el-sub-menu__title .el-sub-menu__icon-arrow),
:deep(.navigation-surface .menu .el-sub-menu.is-active > .el-sub-menu__title .el-sub-menu__icon-arrow) {
  color: #f8fafc;
}

:deep(.navigation-surface .menu .el-menu-item:focus-visible),
:deep(.navigation-surface .menu .el-sub-menu__title:focus-visible) {
  outline: 2px solid #60a5fa;
  outline-offset: -2px;
}

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
  min-width: 0;
}

.header-user__identity {
  display: flex;
  flex-direction: column;
  min-width: 132px;
}

.header-user__identity strong {
  overflow: hidden;
  color: #172033;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-user__identity span { color: #718096; font-size: 11px; }
.mobile-menu-button { display: none; width: 36px; min-width: 36px; padding: 0; font-size: 20px; }
.app-main { min-width: 0; padding: 20px; overflow-x: auto; }

@media (max-width: 900px) {
  .desktop-sidebar { display: none; }
  .mobile-menu-button { display: inline-flex; }
  .app-header { padding: 0 12px; }
  .app-main { width: 100%; padding: 14px; }
  .header-user__identity span { display: none; }
  .header-user { gap: 6px; }
  .header-user__identity { width: 76px; min-width: 0; }
  .header-user .el-button { min-width: 36px; padding: 4px; }
}
</style>
