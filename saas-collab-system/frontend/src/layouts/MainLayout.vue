<template>
  <el-container class="app-shell">
    <el-aside width="240px" class="app-sidebar desktop-sidebar">
      <div class="brand">SaaS 协同系统</div>
      <el-menu router :default-active="$route.path" class="menu">
        <template v-for="item in menuItems" :key="item.path || item.label">
          <el-sub-menu v-if="item.children" :index="item.label">
            <template #title>{{ item.label }}</template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">{{ child.label }}</el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="item.path">{{ item.label }}</el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div class="header-context">
          <el-button class="mobile-menu-button" text aria-label="打开导航菜单" @click="mobileMenuOpen = true">☰</el-button>
          <span>阶段3 Mock / API 切换环境</span>
        </div>
        <span>{{ auth.currentUser.username }} / {{ auth.currentUser.user_type }}</span>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
    <el-drawer v-model="mobileMenuOpen" direction="ltr" size="280px" :with-header="false" class="mobile-nav-drawer">
      <div class="brand">SaaS 协同系统</div>
      <el-menu router :default-active="$route.path" class="menu" @select="mobileMenuOpen = false">
        <template v-for="item in menuItems" :key="item.path || item.label">
          <el-sub-menu v-if="item.children" :index="`mobile-${item.label}`">
            <template #title>{{ item.label }}</template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">{{ child.label }}</el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="item.path">{{ item.label }}</el-menu-item>
        </template>
      </el-menu>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { ref } from 'vue';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const mobileMenuOpen = ref(false);

// 菜单只负责导航展示，不代表真实授权结果；权限以后端返回为准。
const menuItems = [
  { path: '/', label: '首页' },
  {
    label: '经营分析',
    children: [
      { path: '/analytics/sales', label: '销售分析' },
      { path: '/analytics/inventory', label: '库存分析' }
    ]
  },
  {
    label: '经营决策',
    children: [
      { path: '/inventory/alerts', label: '库存预警' },
      { path: '/inventory/replenishment', label: '补货建议' },
      { path: '/lifecycle/reviews', label: '生命周期复盘' },
      { path: '/lifecycle/history', label: '复盘历史' },
      { path: '/alerts/business', label: '经营预警' }
    ]
  },
  { path: '/products/research', label: '新品市调' },
  { path: '/products/master', label: '商品主数据' },
  { path: '/purchasing/orders', label: '采购供应链' },
  { path: '/suppliers/tasks', label: '供应商协同' },
  { path: '/listings/sites', label: '多国家刊登' },
  { path: '/pricing/prices', label: '价格中心' },
  { path: '/rpa/tasks', label: 'RPA任务' },
  { path: '/integrations/api-sync', label: 'API同步' },
  {
    label: '财务中心',
    children: [
      { path: '/finance/analytics', label: '财务分析' },
      { path: '/finance/statements', label: '平台账单' },
      { path: '/finance/reconciliation/matches', label: '对账差异' }
    ]
  },
  {
    label: '报表中心',
    children: [
      { path: '/reports/basic', label: '基础报表' },
      { path: '/reports/exports', label: '报表导出' }
    ]
  },
  {
    label: '系统治理',
    children: [
      { path: '/settings/config-center', label: '配置中心' },
      { path: '/settings/config-versions', label: '配置版本' }
    ]
  },
  { path: '/audit/operations', label: '日志审计' }
];
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.app-sidebar {
  border-right: 1px solid #d9e2ec;
  background: #fff;
}

.brand {
  height: 56px;
  padding: 18px 20px;
  font-weight: 700;
  border-bottom: 1px solid #d9e2ec;
}

.menu {
  border-right: 0;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  border-bottom: 1px solid #d9e2ec;
  background: #fff;
}

.header-context {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mobile-menu-button {
  display: none;
  width: 36px;
  min-width: 36px;
  padding: 0;
  font-size: 20px;
}

.app-main {
  padding: 20px;
  min-width: 0;
  overflow-x: auto;
}

:deep(.mobile-nav-drawer .el-drawer__body) {
  padding: 0;
}

@media (max-width: 900px) {
  .desktop-sidebar {
    display: none;
  }

  .mobile-menu-button {
    display: inline-flex;
  }

  .app-header {
    padding: 0 12px;
    font-size: 12px;
  }

  .app-main {
    width: 100%;
    padding: 14px;
  }
}
</style>
