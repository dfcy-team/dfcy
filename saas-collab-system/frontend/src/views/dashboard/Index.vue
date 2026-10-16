<template>
  <section class="dashboard-page">
    <h1 class="sr-only">工作台</h1>
    <MonthlySalesProgress />
    <section class="workspace-section">
      <header><h2>常用入口</h2><p>进入当前角色可见的任务页面。</p></header>
      <div class="shortcut-grid">
        <router-link v-for="item in shortcuts" :key="item.path" :to="item.path" class="shortcut-item">
          <strong>{{ item.label }}</strong>
          <span>打开</span>
        </router-link>
      </div>
    </section>

    <section class="workspace-section">
      <header><h2>我的待办与异常</h2><p>查看当前账号的待办、异常与审批汇总。</p></header>
      <AppState
        status="empty"
        title="待办汇总暂未接入"
        detail="您可以通过常用入口查看各业务页面的当前进度。"
        action-label="查看可用入口"
        @action="scrollToShortcuts"
      />
    </section>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import AppState from '../../components/AppState.vue';
import MonthlySalesProgress from './MonthlySalesProgress.vue';
import { useAuthStore } from '../../stores/auth';
import { filterMenuItems, flattenMenuItems } from '../../router/menu';

const auth = useAuthStore();
const shortcuts = computed(() => flattenMenuItems(filterMenuItems(auth.currentUser)).filter((item) => item.path !== '/').slice(0, 8));

function scrollToShortcuts() {
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  document.querySelector('.shortcut-grid')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' });
}
</script>

<style scoped>
.shortcut-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.shortcut-item {
  min-height: 112px;
  padding: 16px;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}

.shortcut-item span { color: #718096; }
.workspace-section { margin-top: 22px; }
.workspace-section:first-of-type { margin-top: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.workspace-section header { margin-bottom: 12px; }
.workspace-section h2 { margin: 0; color: #172033; font-size: 17px; }
.workspace-section header p { margin: 5px 0 0; color: #718096; font-size: 13px; }

.shortcut-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.shortcut-item:hover { border-color: #4b88b8; background: #f7fbff; }
.shortcut-item:focus-visible { border-color: #2563eb; outline: 2px solid #2563eb; outline-offset: 2px; }
.shortcut-item strong { color: #24364b; font-size: 14px; }
.shortcut-item span { font-size: 12px; }

@media (max-width: 1000px) {
  .shortcut-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 560px) {
  .shortcut-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .shortcut-item { min-height: 70px; padding: 12px; gap: 8px; }
  .shortcut-item strong { font-size: 13px; }
  .shortcut-item span { flex-shrink: 0; }
}
</style>
