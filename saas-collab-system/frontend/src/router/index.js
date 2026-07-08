import { createRouter, createWebHistory } from 'vue-router';
import MainLayout from '../layouts/MainLayout.vue';
import Login from '../views/auth/Login.vue';
import Dashboard from '../views/dashboard/Index.vue';
import ResearchList from '../views/products/ResearchList.vue';
import ResearchDetail from '../views/products/ResearchDetail.vue';
import ProductMasterList from '../views/products/ProductMasterList.vue';
import ProductMasterDetail from '../views/products/ProductMasterDetail.vue';
import ProductStatusList from '../views/products/ProductStatusList.vue';
import PurchaseOrderList from '../views/purchasing/PurchaseOrderList.vue';
import PurchaseOrderDetail from '../views/purchasing/PurchaseOrderDetail.vue';
import SupplierTaskList from '../views/suppliers/SupplierTaskList.vue';
import SupplierTaskDetail from '../views/suppliers/SupplierTaskDetail.vue';
import SupplierShipmentList from '../views/suppliers/SupplierShipmentList.vue';
import SupplierShipmentDetail from '../views/suppliers/SupplierShipmentDetail.vue';
import SiteProfileList from '../views/listings/SiteProfileList.vue';
import SiteProfileDetail from '../views/listings/SiteProfileDetail.vue';
import ListingTemplateList from '../views/listings/ListingTemplateList.vue';
import PriceList from '../views/pricing/PriceList.vue';
import PriceDetail from '../views/pricing/PriceDetail.vue';
import RPATaskList from '../views/rpa/RPATaskList.vue';
import RPATaskDetail from '../views/rpa/RPATaskDetail.vue';
import APISyncTaskList from '../views/integrations/APISyncTaskList.vue';
import APISyncLogList from '../views/integrations/APISyncLogList.vue';
import OperationLogList from '../views/audit/OperationLogList.vue';
import FinanceImportList from '../views/finance/FinanceImportList.vue';
import BasicReportIndex from '../views/reports/BasicReportIndex.vue';

const routes = [
  { path: '/login', component: Login, meta: { public: true } },
  {
    path: '/',
    component: MainLayout,
    children: [
      { path: '', component: Dashboard },
      { path: 'products/research', component: ResearchList },
      { path: 'products/research/:id', component: ResearchDetail },
      { path: 'products/master', component: ProductMasterList },
      { path: 'products/master/:id', component: ProductMasterDetail },
      { path: 'products/status', component: ProductStatusList },
      { path: 'purchasing/orders', component: PurchaseOrderList },
      { path: 'purchasing/orders/:id', component: PurchaseOrderDetail },
      { path: 'suppliers/tasks', component: SupplierTaskList },
      { path: 'suppliers/tasks/:id', component: SupplierTaskDetail },
      { path: 'suppliers/shipments', component: SupplierShipmentList },
      { path: 'suppliers/shipments/:id', component: SupplierShipmentDetail },
      { path: 'listings/sites', component: SiteProfileList },
      { path: 'listings/sites/:id', component: SiteProfileDetail },
      { path: 'listings/templates', component: ListingTemplateList },
      { path: 'pricing/prices', component: PriceList },
      { path: 'pricing/prices/:id', component: PriceDetail },
      { path: 'rpa/tasks', component: RPATaskList },
      { path: 'rpa/tasks/:id', component: RPATaskDetail },
      { path: 'integrations/api-sync', component: APISyncTaskList },
      { path: 'integrations/api-sync/logs', component: APISyncLogList },
      { path: 'finance/imports', component: FinanceImportList },
      { path: 'reports/basic', component: BasicReportIndex },
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
