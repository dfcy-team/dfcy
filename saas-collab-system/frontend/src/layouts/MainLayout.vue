<template>
  <el-container class="app-shell">
    <el-aside width="248px" class="app-sidebar desktop-sidebar">
      <div class="navigation-surface">
        <div class="brand">
          <strong>业务协同工作台</strong>
        </div>
        <div class="sidebar-menu-scroll">
          <AppMenu :items="visibleMenuItems" />
        </div>
      </div>
    </el-aside>

    <el-container class="app-workspace">
      <el-header class="app-header">
        <div class="header-primary">
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
              <strong :title="auth.currentUser?.username">{{ auth.currentUser?.full_name || auth.currentUser?.username }}</strong>
              <span>{{ roleLabel }}</span>
            </div>
            <el-button class="user-settings-button" text @click="userSettingsOpen = true">个人设置</el-button>
            <el-button text @click="handleLogout">退出登录</el-button>
          </div>
        </div>

        <nav class="route-tabs" aria-label="已打开页面" role="tablist">
          <button
            v-for="tab in openTabs"
            :key="tab.path"
            class="route-tab"
            :class="{ 'is-active': route.fullPath === tab.path }"
            role="tab"
            :aria-selected="route.fullPath === tab.path"
            :draggable="true"
            :title="tab.closable
              ? `${tab.label}：可以移动TAB页，可以关闭TAB页`
              : `${tab.label}：可以移动TAB页，固定页签不可关闭`"
            @click="activateTab(tab.path)"
            @dragstart="startTabDrag(tab.path, $event)"
            @dragover.prevent
            @drop.prevent="dropTab(tab.path)"
            @dragend="clearTabDrag"
          >
            <span class="route-tab__label">{{ tab.label }}</span>
            <span
              v-if="tab.closable"
              class="route-tab__close"
              role="button"
              :aria-label="`关闭${tab.label}`"
              @click.stop="closeTab(tab.path)"
            >×</span>
          </button>
        </nav>
      </el-header>

      <el-main ref="mainScrollContainer" class="app-main" @scroll="updateScrollControls">
        <router-view />
        <div class="main-scroll-controls" aria-label="内容滚动控制">
          <button v-if="canScrollUp" type="button" aria-label="回到顶部" title="回到顶部" @click="scrollMainTo('top')">↑</button>
          <button v-if="canScrollDown" type="button" aria-label="滚动到底部" title="滚动到底部" @click="scrollMainTo('bottom')">↓</button>
        </div>
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
          <strong>业务协同工作台</strong>
        </div>
        <div class="sidebar-menu-scroll">
          <AppMenu :items="visibleMenuItems" @select="mobileMenuOpen = false" />
        </div>
      </div>
    </el-drawer>

    <UserSettingsDrawer
      v-model="userSettingsOpen"
      :current-user="auth.currentUser"
      :tab-limit="tabLimit"
      :open-tab-count="openTabs.length"
      @profile-updated="handleProfileUpdated"
      @password-changed="handlePasswordChanged"
      @tab-limit-changed="handleTabLimitChanged"
    />
  </el-container>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMenu, ElMenuItem, ElMessage, ElSubMenu } from 'element-plus';
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
import UserSettingsDrawer from '../components/UserSettingsDrawer.vue';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const mobileMenuOpen = ref(false);
const userSettingsOpen = ref(false);
const mainScrollContainer = ref(null);
const canScrollUp = ref(false);
const canScrollDown = ref(false);
const tabsStorageKey = 'business-workbench:open-tabs';
const defaultTabLimit = 15;
const homeTab = { path: '/', label: '工作台', closable: false };

function tabLimitStorageKey() {
  return `business-workbench:tab-limit:${auth.currentUser?.username || 'anonymous'}`;
}

function loadTabLimit() {
  const storedLimit = Number(localStorage.getItem(tabLimitStorageKey()));
  return Number.isInteger(storedLimit) && storedLimit >= 5 && storedLimit <= 30
    ? storedLimit
    : defaultTabLimit;
}

function loadOpenTabs() {
  try {
    const storedTabs = JSON.parse(sessionStorage.getItem(tabsStorageKey) || '[]');
    if (!Array.isArray(storedTabs)) return [homeTab];
    const validTabs = storedTabs.filter((tab) => tab?.path && tab?.label);
    return [homeTab, ...validTabs.filter((tab) => tab.path !== '/')];
  } catch {
    return [homeTab];
  }
}

const openTabs = ref(loadOpenTabs());
const tabLimit = ref(loadTabLimit());
const draggedTabPath = ref(null);
const menuRenderVersion = ref(0);
let contentObserver;
let removeTabLimitGuard;

const visibleMenuItems = computed(() => filterMenuItems(auth.currentUser));
const currentLabel = computed(() => findMenuLabel(route.path, visibleMenuItems.value));
const roleLabel = computed(() => {
  if (auth.currentUser?.identity_label) return auth.currentUser.identity_label;
  if (auth.currentUser?.is_superuser) return '平台超级管理员';
  const roles = auth.currentUser?.roles?.filter(Boolean) || [];
  return roles.length ? roles.join(' / ') : '未分配角色';
});

function updateOpenTabs(currentRoute) {
  const path = currentRoute.fullPath;
  if (!openTabs.value.some((tab) => tab.path === path)) {
    openTabs.value.push({
      path,
      label: currentLabel.value || currentRoute.meta?.title || currentRoute.path,
      closable: path !== '/'
    });
  }
  nextTick(updateScrollControls);
}

watch(() => route.fullPath, () => updateOpenTabs(route), { immediate: true });
watch(openTabs, (tabs) => {
  sessionStorage.setItem(tabsStorageKey, JSON.stringify(tabs));
}, { deep: true });

function activateTab(path) {
  if (path !== route.fullPath) router.push(path);
}

function closeTab(path) {
  const index = openTabs.value.findIndex((tab) => tab.path === path);
  if (index < 0 || path === '/') return;
  const wasActive = route.fullPath === path;
  openTabs.value.splice(index, 1);
  if (wasActive) {
    const nextTab = openTabs.value[Math.max(0, index - 1)] || openTabs.value[0];
    router.push(nextTab.path);
  }
}

function startTabDrag(path, event) {
  draggedTabPath.value = path;
  event.dataTransfer?.setData('text/plain', path);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
}

function dropTab(targetPath) {
  const sourcePath = draggedTabPath.value;
  draggedTabPath.value = null;
  if (!sourcePath || sourcePath === targetPath) return;
  const sourceIndex = openTabs.value.findIndex((tab) => tab.path === sourcePath);
  const targetIndex = openTabs.value.findIndex((tab) => tab.path === targetPath);
  if (sourceIndex < 0 || targetIndex < 0) return;
  const [tab] = openTabs.value.splice(sourceIndex, 1);
  openTabs.value.splice(targetIndex, 0, tab);
}

function clearTabDrag() {
  draggedTabPath.value = null;
}

function getMainScrollElement() {
  return mainScrollContainer.value?.$el || mainScrollContainer.value;
}

function updateScrollControls() {
  const element = getMainScrollElement();
  if (!element) return;
  canScrollUp.value = element.scrollTop > 4;
  canScrollDown.value = element.scrollTop + element.clientHeight < element.scrollHeight - 4;
}

function scrollMainTo(direction) {
  const element = getMainScrollElement();
  if (!element) return;
  element.scrollTo({ top: direction === 'top' ? 0 : element.scrollHeight, behavior: 'smooth' });
}

onMounted(() => {
  removeTabLimitGuard = router.beforeEach((to) => {
    const alreadyOpen = openTabs.value.some((tab) => tab.path === to.fullPath);
    if (alreadyOpen || openTabs.value.length < tabLimit.value) return true;
    ElMessage.warning(`最多可打开 ${tabLimit.value} 个页签，请先关闭不需要的页签后再试。`);
    return false;
  });
  nextTick(updateScrollControls);
  window.addEventListener('resize', updateScrollControls);
  const scrollElement = getMainScrollElement();
  if (typeof MutationObserver !== 'undefined' && scrollElement) {
    contentObserver = new MutationObserver(() => nextTick(updateScrollControls));
    contentObserver.observe(scrollElement, { childList: true, subtree: true });
  }
});

onBeforeUnmount(() => {
  removeTabLimitGuard?.();
  window.removeEventListener('resize', updateScrollControls);
  contentObserver?.disconnect();
});

function handleLogout() {
  auth.logout();
  router.replace('/login');
}

function handleProfileUpdated(profile) {
  auth.setCurrentUser({ ...auth.currentUser, ...profile });
}

function handleTabLimitChanged(limit) {
  const normalizedLimit = Math.min(30, Math.max(5, Number(limit) || defaultTabLimit));
  tabLimit.value = normalizedLimit;
  localStorage.setItem(tabLimitStorageKey(), String(normalizedLimit));
  ElMessage.success(`最大打开页签数已设置为 ${normalizedLimit} 个。`);
}

function handlePasswordChanged() {
  userSettingsOpen.value = false;
  auth.logout();
  ElMessage.success('密码已修改，请使用新密码重新登录。');
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
      return h(ElMenuItem, {
        index: item.path,
        onClick: async () => {
          const navigationFailure = await router.push(item.path);
          if (navigationFailure) menuRenderVersion.value += 1;
          else emit('select');
        }
      }, () => item.label);
    };
    return () => h(ElMenu, {
      key: `${route.path}:${menuRenderVersion.value}`,
      defaultActive: route.path,
      class: 'menu'
    }, () => props.items.map(renderItem));
  }
});
</script>

<style scoped>
.app-shell { height: 100vh; overflow: hidden; }
.app-workspace { width: calc(100% - 248px); min-width: 0; height: 100vh; min-height: 0; margin-left: 248px; }

.app-sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 20;
  width: 248px;
  height: 100vh;
  border-right: 1px solid #263449;
  background: #101827;
}

.navigation-surface {
  display: flex;
  flex-direction: column;
  height: 100%;
  color: #cbd5e1;
  background: #101827;
}

.sidebar-menu-scroll { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; }

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
  flex-direction: column;
  align-items: stretch;
  height: 104px;
  padding: 0;
  border-bottom: 1px solid #d9e2ec;
  background: #fff;
}

.header-primary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 56px;
  padding: 0 20px;
}

.header-context,
.header-user {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.route-tabs {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 4px;
  flex: 0 0 48px;
  min-width: 0;
  overflow-x: auto;
  padding: 7px 20px;
  border-top: 1px solid #edf0f4;
  background: #f8fafc;
}

.route-tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  max-width: 180px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid #d9dee7;
  border-radius: 5px;
  color: #334155;
  background: linear-gradient(#fff, #f3f4f6);
  box-shadow: 0 1px 2px rgb(15 23 42 / 6%);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
}
.route-tab:hover { border-color: #aeb8c6; background: #fff; }
.route-tab.is-active { border-color: #334155; color: #fff; background: #334155; font-weight: 600; }
.route-tab__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.route-tab__close { color: #94a3b8; font-size: 17px; line-height: 1; }
.route-tab__close:hover { color: #dc2626; }
.route-tab.is-active .route-tab__close { color: #dbe4ef; }
.route-tab.is-active .route-tab__close:hover { color: #fff; }

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
.app-main { position: relative; min-width: 0; height: calc(100vh - 104px); padding: 20px; overflow: auto; }
.main-scroll-controls { position: fixed; z-index: 30; right: 18px; bottom: 18px; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.main-scroll-controls button { width: 32px; height: 32px; border: 1px solid #cbd5e1; border-radius: 50%; color: #334155; background: #fff; box-shadow: 0 2px 8px rgb(15 23 42 / 14%); cursor: pointer; pointer-events: auto; }

@media (max-width: 900px) {
  .desktop-sidebar { display: none; }
  .app-workspace { width: 100%; margin-left: 0; }
  .mobile-menu-button { display: inline-flex; }
  .header-context :deep(.el-breadcrumb) { display: none; }
  .header-primary { padding: 0 12px; }
  .app-main { width: 100%; padding: 14px; }
  .route-tabs { padding: 7px 12px; }
  .header-user__identity { display: none; }
  .header-user { gap: 6px; }
  .user-settings-button { min-width: 36px; padding: 4px; }
  .header-user .el-button { min-width: 36px; padding: 4px; font-size: 12px; }
}
</style>
