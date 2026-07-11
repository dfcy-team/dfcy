import { createRouter, createWebHistory } from 'vue-router';
const MainLayout = () => import('../layouts/MainLayout.vue');
const Login = () => import('../views/auth/Login.vue');
const Dashboard = () => import('../views/dashboard/Index.vue');
const SalesAnalysis = () => import('../views/analytics/SalesAnalysis.vue');
const InventoryAnalysis = () => import('../views/analytics/InventoryAnalysis.vue');
const InventoryAlertList = () => import('../views/inventory/InventoryAlertList.vue');
const ReplenishmentSuggestionList = () => import('../views/inventory/ReplenishmentSuggestionList.vue');
const LifecycleReviewList = () => import('../views/lifecycle/LifecycleReviewList.vue');
const LifecycleReviewHistory = () => import('../views/lifecycle/LifecycleReviewHistory.vue');
const BusinessAlertList = () => import('../views/alerts/BusinessAlertList.vue');
const ResearchList = () => import('../views/products/ResearchList.vue');
const ResearchDetail = () => import('../views/products/ResearchDetail.vue');
const ProductMasterList = () => import('../views/products/ProductMasterList.vue');
const ProductMasterDetail = () => import('../views/products/ProductMasterDetail.vue');
const ProductStatusList = () => import('../views/products/ProductStatusList.vue');
const ProductStatusDashboard = () => import('../views/products/ProductStatusDashboard.vue');
const ProductStatusRecommendationList = () => import('../views/products/ProductStatusRecommendationList.vue');
const ProductStatusRecommendationDetail = () => import('../views/products/ProductStatusRecommendationDetail.vue');
const ProductStatusTransitionHistory = () => import('../views/products/ProductStatusTransitionHistory.vue');
const PurchaseOrderList = () => import('../views/purchasing/PurchaseOrderList.vue');
const PurchaseOrderDetail = () => import('../views/purchasing/PurchaseOrderDetail.vue');
const SupplierTaskList = () => import('../views/suppliers/SupplierTaskList.vue');
const SupplierTaskDetail = () => import('../views/suppliers/SupplierTaskDetail.vue');
const SupplierShipmentList = () => import('../views/suppliers/SupplierShipmentList.vue');
const SupplierShipmentDetail = () => import('../views/suppliers/SupplierShipmentDetail.vue');
const SupplierPerformanceDashboard = () => import('../views/suppliers/SupplierPerformanceDashboard.vue');
const SupplierPerformanceList = () => import('../views/suppliers/SupplierPerformanceList.vue');
const SupplierPerformanceDetail = () => import('../views/suppliers/SupplierPerformanceDetail.vue');
const MySupplierPerformance = () => import('../views/suppliers/MySupplierPerformance.vue');
const MySupplierPerformanceHistory = () => import('../views/suppliers/MySupplierPerformanceHistory.vue');
const SiteProfileList = () => import('../views/listings/SiteProfileList.vue');
const SiteProfileDetail = () => import('../views/listings/SiteProfileDetail.vue');
const ListingTemplateList = () => import('../views/listings/ListingTemplateList.vue');
const PriceList = () => import('../views/pricing/PriceList.vue');
const PriceDetail = () => import('../views/pricing/PriceDetail.vue');
const RPATaskList = () => import('../views/rpa/RPATaskList.vue');
const RPATaskDetail = () => import('../views/rpa/RPATaskDetail.vue');
const RPAStabilityDashboard = () => import('../views/rpa/RPAStabilityDashboard.vue');
const RPAAttemptList = () => import('../views/rpa/RPAAttemptList.vue');
const RPAAttemptDetail = () => import('../views/rpa/RPAAttemptDetail.vue');
const RPAManualQueue = () => import('../views/rpa/RPAManualQueue.vue');
const RPAAccountLockList = () => import('../views/rpa/RPAAccountLockList.vue');
const RPAPageSignatureAlertList = () => import('../views/rpa/RPAPageSignatureAlertList.vue');
const APISyncTaskList = () => import('../views/integrations/APISyncTaskList.vue');
const APISyncLogList = () => import('../views/integrations/APISyncLogList.vue');
const IntegrationConfigList = () => import('../views/integrations/IntegrationConfigList.vue');
const IntegrationConfigDetail = () => import('../views/integrations/IntegrationConfigDetail.vue');
const SyncJobList = () => import('../views/integrations/SyncJobList.vue');
const SyncRunList = () => import('../views/integrations/SyncRunList.vue');
const SyncRunDetail = () => import('../views/integrations/SyncRunDetail.vue');
const OperationLogList = () => import('../views/audit/OperationLogList.vue');
const FinanceImportList = () => import('../views/finance/FinanceImportList.vue');
const PlatformStatementList = () => import('../views/finance/PlatformStatementList.vue');
const WithdrawalRecordList = () => import('../views/finance/WithdrawalRecordList.vue');
const BankReceiptList = () => import('../views/finance/BankReceiptList.vue');
const ReconciliationMatchList = () => import('../views/finance/ReconciliationMatchList.vue');
const ReconciliationMatchDetail = () => import('../views/finance/ReconciliationMatchDetail.vue');
const ReconciliationExceptionList = () => import('../views/finance/ReconciliationExceptionList.vue');
const BasicReportIndex = () => import('../views/reports/BasicReportIndex.vue');
const PlatformAccessRisk = () => import('../views/settings/PlatformAccessRisk.vue');
const PlatformIntegrationReadiness = () => import('../views/settings/PlatformIntegrationReadiness.vue');
const SecurityReviewChecklist = () => import('../views/settings/SecurityReviewChecklist.vue');
const ConfigCenterList = () => import('../views/settings/ConfigCenterList.vue');
const ConfigVersionHistory = () => import('../views/settings/ConfigVersionHistory.vue');

const routes = [
  { path: '/login', component: Login, meta: { public: true } },
  {
    path: '/',
    component: MainLayout,
    children: [
      { path: '', component: Dashboard },
      { path: 'analytics/sales', component: SalesAnalysis },
      { path: 'analytics/inventory', component: InventoryAnalysis },
      { path: 'inventory/alerts', component: InventoryAlertList },
      { path: 'inventory/replenishment', component: ReplenishmentSuggestionList },
      { path: 'lifecycle/reviews', component: LifecycleReviewList },
      { path: 'lifecycle/history', component: LifecycleReviewHistory },
      { path: 'alerts/business', component: BusinessAlertList },
      { path: 'products/research', component: ResearchList },
      { path: 'products/research/:id', component: ResearchDetail },
      { path: 'products/master', component: ProductMasterList },
      { path: 'products/master/:id', component: ProductMasterDetail },
      { path: 'products/status', component: ProductStatusList },
      { path: 'products/status-dashboard', component: ProductStatusDashboard },
      { path: 'products/status-recommendations', component: ProductStatusRecommendationList },
      { path: 'products/status-recommendations/:id', component: ProductStatusRecommendationDetail },
      { path: 'products/status-transitions', component: ProductStatusTransitionHistory },
      { path: 'purchasing/orders', component: PurchaseOrderList },
      { path: 'purchasing/orders/:id', component: PurchaseOrderDetail },
      { path: 'suppliers/tasks', component: SupplierTaskList },
      { path: 'suppliers/tasks/:id', component: SupplierTaskDetail },
      { path: 'suppliers/shipments', component: SupplierShipmentList },
      { path: 'suppliers/shipments/:id', component: SupplierShipmentDetail },
      { path: 'suppliers/performance', component: SupplierPerformanceDashboard },
      { path: 'suppliers/performance/list', component: SupplierPerformanceList },
      { path: 'suppliers/performance/:supplierId', component: SupplierPerformanceDetail },
      { path: 'suppliers/my-performance', component: MySupplierPerformance },
      { path: 'suppliers/my-performance/history', component: MySupplierPerformanceHistory },
      { path: 'listings/sites', component: SiteProfileList },
      { path: 'listings/sites/:id', component: SiteProfileDetail },
      { path: 'listings/templates', component: ListingTemplateList },
      { path: 'pricing/prices', component: PriceList },
      { path: 'pricing/prices/:id', component: PriceDetail },
      { path: 'rpa/tasks', component: RPATaskList },
      { path: 'rpa/tasks/:id', component: RPATaskDetail },
      { path: 'rpa/stability', component: RPAStabilityDashboard },
      { path: 'rpa/attempts', component: RPAAttemptList },
      { path: 'rpa/attempts/:id', component: RPAAttemptDetail },
      { path: 'rpa/manual-queue', component: RPAManualQueue },
      { path: 'rpa/account-locks', component: RPAAccountLockList },
      { path: 'rpa/page-signatures', component: RPAPageSignatureAlertList },
      { path: 'integrations/configs', component: IntegrationConfigList },
      { path: 'integrations/configs/:id', component: IntegrationConfigDetail },
      { path: 'integrations/sync-jobs', component: SyncJobList },
      { path: 'integrations/sync-runs', component: SyncRunList },
      { path: 'integrations/sync-runs/:id', component: SyncRunDetail },
      { path: 'integrations/api-sync', component: APISyncTaskList },
      { path: 'integrations/api-sync/logs', component: APISyncLogList },
      { path: 'finance/imports', component: FinanceImportList },
      { path: 'finance/statements', component: PlatformStatementList },
      { path: 'finance/withdrawals', component: WithdrawalRecordList },
      { path: 'finance/bank-receipts', component: BankReceiptList },
      { path: 'finance/reconciliation/matches', component: ReconciliationMatchList },
      { path: 'finance/reconciliation/matches/:id', component: ReconciliationMatchDetail },
      { path: 'finance/reconciliation/exceptions', component: ReconciliationExceptionList },
      { path: 'reports/basic', component: BasicReportIndex },
      { path: 'settings/platform-risk', component: PlatformAccessRisk },
      { path: 'settings/platform-readiness', component: PlatformIntegrationReadiness },
      { path: 'settings/security-review', component: SecurityReviewChecklist },
      { path: 'settings/config-center', component: ConfigCenterList },
      { path: 'settings/config-versions', component: ConfigVersionHistory },
      { path: 'audit/operations', component: OperationLogList }
    ]
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

router.beforeEach((to) => {
  // 阶段0路由守卫仅占位，不做真实权限判断；真实权限以后端 /api/internal/auth/me/ 返回为准。
  if (to.meta.public) {
    return true;
  }
  return true;
});

export default router;
