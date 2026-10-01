<template>
  <AppPage
    :title="workspace.title"
    :subtitle="workspace.subtitle"
    eyebrow="ROLE WORKSPACE"
    :capability="useMock ? 'mock' : 'connected'"
    boundary-note="工作台只展示后端授权范围；指标和建议不直接触发采购、改价、RPA或资金动作。"
  >
    <section class="context-grid" aria-label="当前访问上下文">
      <article>
        <span>认证状态</span>
        <strong>有效</strong>
        <small>{{ useMock ? '模拟会话' : '已登录' }}</small>
      </article>
      <article>
        <span>租户</span>
        <strong>{{ auth.currentUser?.tenant_id }}</strong>
        <small>仅显示当前租户内的数据</small>
      </article>
      <article>
        <span>数据范围</span>
        <strong>{{ dataScopeLabel }}</strong>
        <small>由当前账号授权范围决定</small>
      </article>
      <article>
        <span>可用入口</span>
        <strong>{{ shortcuts.length }}</strong>
        <small>按当前角色权限展示</small>
      </article>
    </section>

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
  </AppPage>
</template>

<script setup>
import { computed } from 'vue';
import AppPage from '../../components/AppPage.vue';
import AppState from '../../components/AppState.vue';
import { useAuthStore } from '../../stores/auth';
import { useMock } from '../../api/request';
import { filterMenuItems, flattenMenuItems } from '../../router/menu';
import { resolveWorkspace, summarizeDataScope } from '../../utils/workspace';

const auth = useAuthStore();
const workspace = computed(() => resolveWorkspace(auth.currentUser));
const dataScopeLabel = computed(() => summarizeDataScope(auth.currentUser));
const shortcuts = computed(() => flattenMenuItems(filterMenuItems(auth.currentUser)).filter((item) => item.path !== '/').slice(0, 8));

function scrollToShortcuts() {
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  document.querySelector('.shortcut-grid')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' });
}
</script>

<style scoped>
.context-grid,
.shortcut-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.context-grid article,
.shortcut-item {
  min-height: 112px;
  padding: 16px;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
  background: #fff;
}

.context-grid article { display: flex; flex-direction: column; }
.context-grid span,
.context-grid small,
.shortcut-item span { color: #718096; }
.context-grid strong { margin: 12px 0 5px; color: #172033; font-size: 20px; }
.context-grid small { font-size: 12px; line-height: 1.6; }
.context-grid strong { overflow-wrap: anywhere; }

.workspace-section { margin-top: 22px; }
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
  .context-grid,
  .shortcut-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 560px) {
  .context-grid,
  .shortcut-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .context-grid article { min-height: 108px; padding: 12px; }
  .context-grid strong { font-size: 17px; margin-top: 8px; }
  .shortcut-item { min-height: 70px; padding: 12px; gap: 8px; }
  .shortcut-item strong { font-size: 13px; }
  .shortcut-item span { flex-shrink: 0; }
}
</style>
