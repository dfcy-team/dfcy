import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { pinia } from '../stores';
import { canAccessPath } from './menu';
const MainLayout = () => import('../layouts/MainLayout.vue');
const Login = () => import('../views/auth/Login.vue');
const Forbidden = () => import('../views/auth/Forbidden.vue');
const Dashboard = () => import('../views/dashboard/Index.vue');
const BusinessOverview = () => import('../views/analytics/BusinessOverview.vue');
const SalesAnalysis = () => import('../views/analytics/SalesAnalysis.vue');
const InventoryAnalysis = () => import('../views/analytics/InventoryAnalysis.vue');
const InventoryAlertList = () => import('../views/inventory/InventoryAlertList.vue');
const ReplenishmentSuggestionList = () => import('../views/inventory/ReplenishmentSuggestionList.vue');
const LifecycleReviewList = () => import('../views/lifecycle/LifecycleReviewList.vue');
const LifecycleReviewHistory = () => import('../views/lifecycle/LifecycleReviewHistory.vue');
const ClearanceRequestList = () => import('../views/lifecycle/ClearanceRequestList.vue');
const BusinessAlertList = () => import('../views/alerts/BusinessAlertList.vue');
const SalesOverview = () => import('../views/sales-management/SalesOverview.vue');
const SalesOrderList = () => import('../views/sales-management/SalesOrderList.vue');
const SalesReturnList = () => import('../views/sales-management/SalesReturnList.vue');
const StoreSalesList = () => import('../views/sales-management/StoreSalesList.vue');
const SkuSalesList = () => import('../views/sales-management/SkuSalesList.vue');
const SalesExportList = () => import('../views/sales-management/SalesExportList.vue');
const SalesDataQualityList = () => import('../views/sales-management/SalesDataQualityList.vue');
const ResearchList = () => import('../views/products/ResearchList.vue');
const ResearchDetail = () => import('../views/products/ResearchDetail.vue');
const ProductMasterList = () => import('../views/products/ProductMasterList.vue');
const ProductMasterDetail = () => import('../views/products/ProductMasterDetail.vue');
const ProductDetailData = () => import('../views/products/ProductDetailData.vue');
const ProductDictionarySettings = () => import('../views/products/ProductDictionarySettings.vue');
const FoundationSettings = () => import('../views/masterdata/FoundationSettings.vue');
const ProductBundleManager = () => import('../views/products/ProductBundleManager.vue');
const ProductStatusList = () => import('../views/products/ProductStatusList.vue');
const ProductStatusDashboard = () => import('../views/products/ProductStatusDashboard.vue');
const ProductStatusRecommendationList = () => import('../views/products/ProductStatusRecommendationList.vue');
const ProductStatusRecommendationDetail = () => import('../views/products/ProductStatusRecommendationDetail.vue');
const ProductStatusTransitionHistory = () => import('../views/products/ProductStatusTransitionHistory.vue');
const PurchaseOrderList = () => import('../views/purchasing/PurchaseOrderList.vue');
const PurchaseOrderDetail = () => import('../views/purchasing/PurchaseOrderDetail.vue');
const SupplyPurchaseOrderConsole = () => import('../views/purchasing/SupplyPurchaseOrderConsole.vue');
const SupplyFlowConsole = () => import('../views/supply-chain/SupplyFlowConsole.vue');
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
const ListingWorkbench = () => import('../views/listings/ListingWorkbench.vue');
const ListingTaskList = () => import('../views/listings/ListingTaskList.vue');
const ListingMappingList = () => import('../views/listings/ListingMappingList.vue');
const ListingLogList = () => import('../views/listings/ListingLogList.vue');
const ListingExceptionList = () => import('../views/listings/ListingExceptionList.vue');
const DevelopmentWorkspace = () => import('../views/development/DevelopmentWorkspace.vue');
const DevelopmentProductArchiveList = () => import('../views/development/DevelopmentProductArchiveList.vue');
const CountrySiteMasterList = () => import('../views/masterdata/CountrySiteMasterList.vue');
const PlatformProductDetailList = () => import('../views/masterdata/PlatformProductDetailList.vue');
const PriceList = () => import('../views/pricing/PriceList.vue');
const PriceDetail = () => import('../views/pricing/PriceDetail.vue');
const RPATaskList = () => import('../views/rpa/RPATaskList.vue');
const RPATaskDetail = () => import('../views/rpa/RPATaskDetail.vue');
const RPAStabilityDashboard = () => import('../views/rpa/RPAStabilityDashboard.vue');
const RPAAttemptList = () => import('../views/rpa/RPAAttemptList.vue');
const RPAAttemptDetail = () => import('../views/rpa/RPAAttemptDetail.vue');
const RPAManualQueue = () => import('../views/rpa/RPAManualQueue.vue');
const RPADeviceList = () => import('../views/rpa/RPADeviceList.vue');
const RPADeviceDetail = () => import('../views/rpa/RPADeviceDetail.vue');
const RPAAccountLockList = () => import('../views/rpa/RPAAccountLockList.vue');
const RPAPageSignatureAlertList = () => import('../views/rpa/RPAPageSignatureAlertList.vue');
const APISyncTaskList = () => import('../views/integrations/APISyncTaskList.vue');
const APISyncLogList = () => import('../views/integrations/APISyncLogList.vue');
const IntegrationConfigDetail = () => import('../views/integrations/IntegrationConfigDetail.vue');
const IntegrationWorkspace = () => import('../views/integrations/IntegrationWorkspace.vue');
const PlatformDrillWorkbench = () => import('../views/integrations/PlatformDrillWorkbench.vue');
const StoreAuthorizationList = () => import('../views/integrations/StoreAuthorizationList.vue');
const IntegrationCapabilityMatrix = () => import('../views/integrations/IntegrationCapabilityMatrix.vue');
const StoreMappingList = () => import('../views/integrations/StoreMappingList.vue');
const ProductMappingList = () => import('../views/integrations/ProductMappingList.vue');
const SyncIncidentList = () => import('../views/integrations/SyncIncidentList.vue');
const IntegrationAuditList = () => import('../views/integrations/IntegrationAuditList.vue');
const PlatformSiteList = () => import('../views/integrations/PlatformSiteList.vue');
const SyncJobList = () => import('../views/integrations/SyncJobList.vue');
const SyncRunDetail = () => import('../views/integrations/SyncRunDetail.vue');
const OperationLogList = () => import('../views/audit/OperationLogList.vue');
const FinanceImportList = () => import('../views/finance/FinanceImportList.vue');
const PlatformStatementList = () => import('../views/finance/PlatformStatementList.vue');
const WithdrawalRecordList = () => import('../views/finance/WithdrawalRecordList.vue');
const BankReceiptList = () => import('../views/finance/BankReceiptList.vue');
const ReconciliationMatchList = () => import('../views/finance/ReconciliationMatchList.vue');
const ReconciliationMatchDetail = () => import('../views/finance/ReconciliationMatchDetail.vue');
const ReconciliationExceptionList = () => import('../views/finance/ReconciliationExceptionList.vue');
const FinanceAnalyticsOverview = () => import('../views/finance/FinanceAnalyticsOverview.vue');
const BasicReportIndex = () => import('../views/reports/BasicReportIndex.vue');
const ReportExportCenter = () => import('../views/reports/ReportExportCenter.vue');
const PlatformAccessRisk = () => import('../views/settings/PlatformAccessRisk.vue');
const PlatformIntegrationReadiness = () => import('../views/settings/PlatformIntegrationReadiness.vue');
const ProductionIntegrationSettings = () => import('../views/settings/ProductionIntegrationSettings.vue');
const SecurityReviewChecklist = () => import('../views/settings/SecurityReviewChecklist.vue');
const ConfigCenterList = () => import('../views/settings/ConfigCenterList.vue');
const ConfigVersionHistory = () => import('../views/settings/ConfigVersionHistory.vue');
const DepartmentDirectory = () => import('../views/system/DepartmentDirectory.vue');
const UserDirectory = () => import('../views/system/UserDirectory.vue');
const RolePermissionMatrix = () => import('../views/system/RolePermissionMatrix.vue');
const SecurityOperations = () => import('../views/system/SecurityOperations.vue');
const PlatformMasterList = () => import('../views/masterdata/PlatformMasterList.vue');
const StoreMasterList = () => import('../views/masterdata/StoreMasterList.vue');
const WarehouseMasterList = () => import('../views/masterdata/WarehouseMasterList.vue');
const SupplierMasterList = () => import('../views/masterdata/SupplierMasterList.vue');
const InfluencerList = () => import('../views/influencers/InfluencerList.vue');
const OutreachTaskList = () => import('../views/influencers/OutreachTaskList.vue');
const SampleFulfillmentList = () => import('../views/influencers/SampleFulfillmentList.vue');
const BdPerformance = () => import('../views/influencers/BdPerformance.vue');
const ApprovalList = () => import('../views/workflow/ApprovalList.vue');
const ApprovalDetail = () => import('../views/workflow/ApprovalDetail.vue');
const ExceptionList = () => import('../views/workflow/ExceptionList.vue');
const ExceptionDetail = () => import('../views/workflow/ExceptionDetail.vue');
const CollaborationEventList = () => import('../views/workflow/CollaborationEventList.vue');
const GovernanceCatalog = () => import('../views/governance/GovernanceCatalog.vue');
const PilotReadiness = () => import('../views/pilot/ReadinessDashboard.vue');
const PilotTopology = () => import('../views/pilot/TopologyOverview.vue');
const PilotWorkflow = () => import('../views/pilot/PilotWorkflow.vue');
const PilotCapacity = () => import('../views/pilot/CapacityDashboard.vue');
const PilotControlRoom = () => import('../views/pilot/ControlRoom.vue');
const PilotSecurityReviews = () => import('../views/pilot/SecurityReviewWorkspace.vue');
const PilotVerificationRuns = () => import('../views/pilot/VerificationRunWorkspace.vue');
const PilotPerformanceRuns = () => import('../views/pilot/PerformanceRunWorkspace.vue');
const PilotEntryDecisions = () => import('../views/pilot/EntryDecisionWorkspace.vue');
const ReleaseContractConsole = () => import('../views/releases/ReleaseContractConsole.vue');

const routes = [
  { path: '/login', component: Login, meta: { public: true } },
  {
    path: '/',
    component: MainLayout,
    children: [
      { path: '', component: Dashboard },
      { path: 'forbidden', component: Forbidden },
      { path: 'analytics/overview', component: BusinessOverview },
      { path: 'analytics/sales', component: SalesAnalysis },
      { path: 'analytics/inventory', component: InventoryAnalysis },
      { path: 'decision/inventory/alerts', component: InventoryAlertList },
      { path: 'decision/inventory/replenishment', component: ReplenishmentSuggestionList },
      { path: 'decision/lifecycle/reviews', component: LifecycleReviewList },
      { path: 'decision/lifecycle/history', component: LifecycleReviewHistory },
      { path: 'decision/lifecycle/clearance-requests', component: ClearanceRequestList },
      { path: 'decision/alerts/business', component: BusinessAlertList },
      { path: 'inventory/alerts', component: InventoryAlertList },
      { path: 'inventory/replenishment', component: ReplenishmentSuggestionList },
      { path: 'lifecycle/reviews', component: LifecycleReviewList },
      { path: 'lifecycle/history', component: LifecycleReviewHistory },
      { path: 'lifecycle/clearance-requests', component: ClearanceRequestList },
      { path: 'alerts/business', component: BusinessAlertList },
      { path: 'sales-management/overview', component: SalesOverview },
      { path: 'sales-management/orders', component: SalesOrderList },
      { path: 'sales-management/returns', component: SalesReturnList },
      { path: 'sales-management/stores', component: StoreSalesList },
      { path: 'sales-management/skus', component: SkuSalesList },
      { path: 'sales-management/exports', component: SalesExportList },
      { path: 'sales-management/data-quality', component: SalesDataQualityList },
      { path: 'workflow/approvals', component: ApprovalList },
      { path: 'workflow/approvals/:id', component: ApprovalDetail },
      { path: 'workflow/exceptions', component: ExceptionList },
      { path: 'workflow/exceptions/:id', component: ExceptionDetail },
      { path: 'workflow/collaboration-events', component: CollaborationEventList },
      { path: 'governance/api-contracts', component: GovernanceCatalog, props: { resource: 'api-contracts' } },
      { path: 'governance/api-contracts/:id', component: GovernanceCatalog, props: { resource: 'api-contracts' } },
      { path: 'governance/assistants', component: GovernanceCatalog, props: { resource: 'assistants' } },
      { path: 'governance/assistants/:id', component: GovernanceCatalog, props: { resource: 'assistants' } },
      { path: 'pilot/readiness', component: PilotReadiness },
      { path: 'pilot/topology', component: PilotTopology },
      { path: 'pilot/recovery', component: PilotWorkflow, props: { kind: 'recovery' } },
      { path: 'pilot/releases', component: PilotWorkflow, props: { kind: 'release' } },
      { path: 'pilot/capacity', component: PilotCapacity },
      { path: 'pilot/control-room', component: PilotControlRoom },
      { path: 'pilot/security-reviews', component: PilotSecurityReviews },
      { path: 'pilot/security-reviews/:id', component: PilotSecurityReviews },
      { path: 'pilot/verification-runs', component: PilotVerificationRuns },
      { path: 'pilot/verification-runs/:id', component: PilotVerificationRuns },
      { path: 'pilot/performance-runs', component: PilotPerformanceRuns },
      { path: 'pilot/performance-runs/:id', component: PilotPerformanceRuns },
      { path: 'pilot/entry-decisions', component: PilotEntryDecisions },
      { path: 'pilot/entry-decisions/:id', component: PilotEntryDecisions },
      { path: 'products/research', component: ResearchList },
      { path: 'products/research/:id', component: ResearchDetail },
      { path: 'products/master', component: ProductMasterList },
      { path: 'products/master/:id', component: ProductMasterDetail },
      { path: 'products/details', component: ProductDetailData },
      { path: 'products/platform-details', component: PlatformProductDetailList },
      { path: 'products/categories', component: ProductDictionarySettings, props: { kind: 'categories' } },
      { path: 'products/attributes', component: ProductDictionarySettings, props: { kind: 'attributes' } },
      { path: 'products/colors', component: ProductDictionarySettings, props: { kind: 'colors' } },
      { path: 'products/specifications', component: ProductDictionarySettings, props: { kind: 'specifications' } },
      { path: 'products/bundles', component: ProductBundleManager },
      { path: 'master-data/settings', component: FoundationSettings },
      { path: 'products/status', component: ProductStatusList },
      { path: 'products/status-dashboard', component: ProductStatusDashboard },
      { path: 'products/status-recommendations', component: ProductStatusRecommendationList },
      { path: 'products/status-recommendations/:id', component: ProductStatusRecommendationDetail },
      { path: 'products/status-transitions', component: ProductStatusTransitionHistory },
      { path: 'purchasing/orders', component: PurchaseOrderList },
      { path: 'purchasing/orders/:id', component: PurchaseOrderDetail },
      { path: 'supply-chain/purchase-orders', component: SupplyPurchaseOrderConsole },
      { path: 'supply-chain/consolidations', component: SupplyFlowConsole, props: { initialTab: 'consolidations' } },
      { path: 'supply-chain/shipments', component: SupplyFlowConsole, props: { initialTab: 'shipments' } },
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
      { path: 'listings/workbench', component: ListingWorkbench },
      { path: 'listings/tasks', component: ListingTaskList },
      { path: 'listings/online-products', component: ListingWorkbench, props: { initialTab: 'online-products' } },
      { path: 'listings/category-mappings', component: ListingMappingList, props: { mappingType: 'category' } },
      { path: 'listings/attribute-mappings', component: ListingMappingList, props: { mappingType: 'attribute' } },
      { path: 'listings/logs', component: ListingLogList },
      { path: 'listings/exceptions', component: ListingExceptionList },
      { path: 'development/requirements', component: DevelopmentWorkspace, props: { mode: 'requirements' } },
      { path: 'development/review', component: DevelopmentWorkspace, props: { mode: 'review' } },
      { path: 'development/projects', component: DevelopmentWorkspace, props: { mode: 'projects' } },
      { path: 'development/projects/archives', component: DevelopmentProductArchiveList },
      { path: 'development/costs', component: DevelopmentWorkspace, props: { mode: 'costs' } },
      { path: 'development/sales', component: DevelopmentWorkspace, props: { mode: 'sales' } },
      { path: 'development/retrospectives', component: DevelopmentWorkspace, props: { mode: 'retrospectives' } },
      { path: 'development/dashboard', component: DevelopmentWorkspace, props: { mode: 'dashboard' } },
      { path: 'pricing/prices', component: PriceList },
      { path: 'pricing/prices/:id', component: PriceDetail },
      { path: 'rpa/tasks', component: RPATaskList },
      { path: 'rpa/tasks/:id', component: RPATaskDetail },
      { path: 'rpa/stability', component: RPAStabilityDashboard },
      { path: 'rpa/runs', component: RPAAttemptList },
      { path: 'rpa/runs/:id', component: RPAAttemptDetail },
      { path: 'rpa/attempts', redirect: '/rpa/runs' },
      { path: 'rpa/attempts/:id', redirect: (to) => `/rpa/runs/${to.params.id}` },
      { path: 'rpa/devices', component: RPADeviceList },
      { path: 'rpa/devices/:id', component: RPADeviceDetail },
      { path: 'rpa/manual-queue', component: RPAManualQueue },
      { path: 'rpa/account-locks', component: RPAAccountLockList },
      { path: 'rpa/page-signatures', component: RPAPageSignatureAlertList },
      { path: 'integrations/configs', component: IntegrationWorkspace, props: { mode: 'configs' } },
      { path: 'integrations/configs/:id', component: IntegrationConfigDetail },
      { path: 'integrations/readiness', component: PlatformIntegrationReadiness },
      { path: 'integrations/production-settings', component: ProductionIntegrationSettings },
      { path: 'integrations/authorizations', component: StoreAuthorizationList },
      { path: 'integrations/capabilities', component: IntegrationCapabilityMatrix },
      { path: 'integrations/store-mappings', component: StoreMappingList },
      { path: 'integrations/product-mappings', component: ProductMappingList },
      { path: 'integrations/incidents', component: SyncIncidentList },
      { path: 'integrations/audit', component: IntegrationAuditList },
      { path: 'integrations/platform-sites', component: PlatformSiteList },
      { path: 'integrations/platform-drill', component: PlatformDrillWorkbench },
      { path: 'integrations/sync-jobs', component: SyncJobList },
      { path: 'integrations/sync-runs', component: IntegrationWorkspace, props: { mode: 'sync-runs', runPermission: 'integrations.run_live_readonly', mockRunPermission: 'integrations.run' } },
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
      { path: 'finance/analytics', component: FinanceAnalyticsOverview },
      { path: 'reports/basic', component: BasicReportIndex },
      { path: 'reports/exports', component: ReportExportCenter },
      { path: 'settings/platform-risk', component: PlatformAccessRisk },
      { path: 'settings/platform-readiness', component: PlatformIntegrationReadiness },
      { path: 'settings/security-review', component: SecurityReviewChecklist },
      { path: 'settings/config-center', component: ConfigCenterList },
      { path: 'settings/config-versions', component: ConfigVersionHistory },
      { path: 'system/departments', component: DepartmentDirectory },
      { path: 'system/users', component: UserDirectory },
      { path: 'system/roles', component: RolePermissionMatrix },
      { path: 'system/security-operations', component: SecurityOperations },
      { path: 'master-data/platforms', component: PlatformMasterList },
      { path: 'master-data/stores', component: StoreMasterList },
      { path: 'master-data/warehouses', component: WarehouseMasterList },
      { path: 'master-data/suppliers', component: SupplierMasterList },
      { path: 'master-data/sites', component: CountrySiteMasterList },
      { path: 'influencers', component: InfluencerList },
      { path: 'influencers/outreach-tasks', component: OutreachTaskList },
      { path: 'influencers/sample-fulfillments', component: SampleFulfillmentList },
      { path: 'influencers/bd-performance', component: BdPerformance },
      { path: 'releases/contracts', component: ReleaseContractConsole },
      { path: 'audit/operations', component: OperationLogList }
    ]
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia);
  await auth.initialize();

  if (to.meta.public) {
    if (to.path === '/login' && auth.isAuthenticated) return '/';
    return true;
  }
  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }
  if (to.path !== '/forbidden' && !canAccessPath(auth.currentUser, to.path)) {
    return '/forbidden';
  }
  return true;
});

export default router;
