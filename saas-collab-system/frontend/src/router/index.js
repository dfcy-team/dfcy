import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '../layouts/MainLayout.vue'
import { useAuthStore } from '../stores/auth'

export const menuRoutes = [
  {
    path: '/dashboard',
    name: 'dashboard',
    meta: {
      title: '首页',
      frontendPermission: 'dashboard:view',
    },
  },
  {
    path: '/products/research',
    name: 'productResearch',
    meta: {
      title: '新品市调',
      frontendPermission: 'products:research:view',
    },
  },
  {
    path: '/products/master',
    name: 'products',
    meta: {
      title: '商品主数据',
      frontendPermission: 'products:view',
    },
  },
  {
    path: '/purchasing',
    name: 'purchasing',
    meta: {
      title: '采购供应链',
      frontendPermission: 'purchasing:view',
    },
  },
  {
    path: '/suppliers/tasks',
    name: 'suppliers',
    meta: {
      title: '供应商协同',
      frontendPermission: 'suppliers:view',
    },
  },
  {
    path: '/listings/site-profiles',
    name: 'listings',
    meta: {
      title: '多国家刊登',
      frontendPermission: 'listings:view',
    },
  },
  {
    path: '/pricing',
    name: 'pricing',
    meta: {
      title: '价格中心',
      frontendPermission: 'pricing:view',
    },
  },
  {
    path: '/rpa',
    name: 'rpa',
    meta: {
      title: 'RPA任务',
      frontendPermission: 'rpa:view',
    },
  },
  {
    path: '/integrations/tasks',
    name: 'integrations',
    meta: {
      title: 'API同步',
      frontendPermission: 'integrations:view',
    },
  },
  {
    path: '/finance/imports',
    name: 'finance',
    meta: {
      title: '财务入口',
      frontendPermission: 'finance:view',
    },
  },
  {
    path: '/reports/basic',
    name: 'reports',
    meta: {
      title: 'BI报表',
      frontendPermission: 'reports:view',
    },
  },
  {
    path: '/audit/operation-logs',
    name: 'audit',
    meta: {
      title: '日志审计',
      frontendPermission: 'audit:view',
    },
  },
]

const mvpRoutes = [
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('../views/dashboard/Index.vue'),
    meta: { title: '首页', frontendPermission: 'dashboard:view' },
  },
  {
    path: '/products/research',
    name: 'productResearch',
    component: () => import('../views/products/ResearchList.vue'),
    meta: { title: '新品市调', frontendPermission: 'products:research:view' },
  },
  {
    path: '/products/research/detail',
    name: 'productResearchDetail',
    component: () => import('../views/products/ResearchDetail.vue'),
    meta: { title: '新品市调详情', frontendPermission: 'products:research:view' },
  },
  {
    path: '/products/master',
    name: 'productMaster',
    component: () => import('../views/products/ProductMasterList.vue'),
    meta: { title: '商品主数据', frontendPermission: 'products:view' },
  },
  {
    path: '/products/master/detail',
    name: 'productMasterDetail',
    component: () => import('../views/products/ProductMasterDetail.vue'),
    meta: { title: '商品主数据详情', frontendPermission: 'products:view' },
  },
  {
    path: '/products/status',
    name: 'productStatus',
    component: () => import('../views/products/ProductStatusList.vue'),
    meta: { title: '商品状态', frontendPermission: 'products:view' },
  },
  {
    path: '/purchasing',
    name: 'purchaseOrders',
    component: () => import('../views/purchasing/PurchaseOrderList.vue'),
    meta: { title: '采购供应链', frontendPermission: 'purchasing:view' },
  },
  {
    path: '/purchasing/detail',
    name: 'purchaseOrderDetail',
    component: () => import('../views/purchasing/PurchaseOrderDetail.vue'),
    meta: { title: '采购订单详情', frontendPermission: 'purchasing:view' },
  },
  {
    path: '/suppliers/tasks',
    name: 'supplierTasks',
    component: () => import('../views/suppliers/SupplierTaskList.vue'),
    meta: { title: '供应商协同', frontendPermission: 'suppliers:view' },
  },
  {
    path: '/suppliers/tasks/detail',
    name: 'supplierTaskDetail',
    component: () => import('../views/suppliers/SupplierTaskDetail.vue'),
    meta: { title: '供应商任务详情', frontendPermission: 'suppliers:view' },
  },
  {
    path: '/suppliers/shipments',
    name: 'supplierShipments',
    component: () => import('../views/suppliers/SupplierShipmentList.vue'),
    meta: { title: '供应商发货', frontendPermission: 'suppliers:view' },
  },
  {
    path: '/suppliers/shipments/detail',
    name: 'supplierShipmentDetail',
    component: () => import('../views/suppliers/SupplierShipmentDetail.vue'),
    meta: { title: '供应商发货详情', frontendPermission: 'suppliers:view' },
  },
  {
    path: '/listings/site-profiles',
    name: 'siteProfiles',
    component: () => import('../views/listings/SiteProfileList.vue'),
    meta: { title: '多国家刊登', frontendPermission: 'listings:view' },
  },
  {
    path: '/listings/site-profiles/detail',
    name: 'siteProfileDetail',
    component: () => import('../views/listings/SiteProfileDetail.vue'),
    meta: { title: '站点资料详情', frontendPermission: 'listings:view' },
  },
  {
    path: '/listings/templates',
    name: 'listingTemplates',
    component: () => import('../views/listings/ListingTemplateList.vue'),
    meta: { title: '刊登模板', frontendPermission: 'listings:view' },
  },
  {
    path: '/pricing',
    name: 'prices',
    component: () => import('../views/pricing/PriceList.vue'),
    meta: { title: '价格中心', frontendPermission: 'pricing:view' },
  },
  {
    path: '/pricing/detail',
    name: 'priceDetail',
    component: () => import('../views/pricing/PriceDetail.vue'),
    meta: { title: '价格详情', frontendPermission: 'pricing:view' },
  },
  {
    path: '/rpa',
    name: 'rpaTasks',
    component: () => import('../views/rpa/RPATaskList.vue'),
    meta: { title: 'RPA任务', frontendPermission: 'rpa:view' },
  },
  {
    path: '/rpa/detail',
    name: 'rpaTaskDetail',
    component: () => import('../views/rpa/RPATaskDetail.vue'),
    meta: { title: 'RPA任务详情', frontendPermission: 'rpa:view' },
  },
  {
    path: '/integrations/tasks',
    name: 'apiSyncTasks',
    component: () => import('../views/integrations/APISyncTaskList.vue'),
    meta: { title: 'API同步', frontendPermission: 'integrations:view' },
  },
  {
    path: '/integrations/logs',
    name: 'apiSyncLogs',
    component: () => import('../views/integrations/APISyncLogList.vue'),
    meta: { title: 'API同步日志', frontendPermission: 'integrations:view' },
  },
  {
    path: '/finance/imports',
    name: 'financeImports',
    component: () => import('../views/finance/FinanceImportList.vue'),
    meta: { title: '财务入口', frontendPermission: 'finance:view' },
  },
  {
    path: '/reports/basic',
    name: 'basicReports',
    component: () => import('../views/reports/BasicReportIndex.vue'),
    meta: { title: 'BI报表', frontendPermission: 'reports:view' },
  },
  {
    path: '/audit/operation-logs',
    name: 'operationLogs',
    component: () => import('../views/audit/OperationLogList.vue'),
    meta: { title: '日志审计', frontendPermission: 'audit:view' },
  },
]

const moduleRoutes = mvpRoutes.map((route) => ({
  ...route,
  meta: {
    ...route.meta,
    requiresAuth: true,
  },
}))

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/auth/Login.vue'),
    meta: {
      guestOnly: true,
    },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: moduleRoutes,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const authStore = useAuthStore()

  // Placeholder guard only. Real authentication and permissions must use the
  // backend response from /api/internal/auth/me/ as the source of truth.
  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    return '/login'
  }

  if (to.meta.guestOnly && authStore.isLoggedIn) {
    return '/dashboard'
  }

  return true
})

export default router
