export const menuItems = [
  { path: '/', label: '工作台' },
  {
    label: '经营分析',
    permissions: ['analytics.view'],
    children: [
      { path: '/analytics/sales', label: '销售分析', permissions: ['analytics.view'] },
      { path: '/analytics/inventory', label: '库存分析', permissions: ['analytics.view'] }
    ]
  },
  {
    label: '经营决策',
    children: [
      { path: '/inventory/alerts', label: '库存预警', permissions: ['alerts.view'] },
      { path: '/inventory/replenishment', label: '补货建议', permissions: ['replenishment.view'] },
      { path: '/lifecycle/reviews', label: '生命周期复盘', permissions: ['products.lifecycle.view'] },
      { path: '/lifecycle/history', label: '复盘历史', permissions: ['products.lifecycle.view'] },
      { path: '/alerts/business', label: '经营预警', permissions: ['alerts.view'] }
    ]
  },
  {
    label: '业务协同',
    internal: true,
    children: [
      { path: '/products/research', label: '新品市调', internal: true },
      { path: '/products/master', label: '商品主数据', internal: true },
      { path: '/purchasing/orders', label: '采购订单', internal: true },
      { path: '/suppliers/performance', label: '供应商绩效', permissions: ['suppliers.performance.view'] },
      { path: '/listings/sites', label: '多国家刊登', internal: true },
      { path: '/pricing/prices', label: '价格中心', internal: true }
    ]
  },
  {
    label: 'RPA协同',
    internal: true,
    children: [
      { path: '/rpa/tasks', label: '任务中心', internal: true },
      { path: '/rpa/attempts', label: '运行记录', internal: true },
      { path: '/rpa/manual-queue', label: '人工队列', internal: true },
      { path: '/rpa/stability', label: '稳定性', internal: true }
    ]
  },
  {
    label: 'API数据接入',
    permissions: ['integrations.view'],
    children: [
      { path: '/integrations/configs', label: '连接配置', permissions: ['integrations.view'] },
      { path: '/integrations/sync-jobs', label: '同步任务', permissions: ['integrations.view'] },
      { path: '/integrations/sync-runs', label: '运行记录', permissions: ['integrations.view'] }
    ]
  },
  {
    label: '财务中心',
    permissions: ['finance.view', 'finance.import'],
    children: [
      { path: '/finance/imports', label: '财务导入', permissions: ['finance.import'] },
      { path: '/finance/analytics', label: '财务分析', permissions: ['finance.view'] },
      { path: '/finance/statements', label: '平台账单', permissions: ['finance.view'] },
      { path: '/finance/withdrawals', label: '提现记录', permissions: ['finance.view'] },
      { path: '/finance/bank-receipts', label: '银行到账', permissions: ['finance.view'] },
      { path: '/finance/reconciliation/exceptions', label: '对账异常', permissions: ['finance.view'] },
      { path: '/finance/reconciliation/matches', label: '对账差异', permissions: ['finance.view'] }
    ]
  },
  {
    label: '报表中心',
    permissions: ['reports.view'],
    children: [
      { path: '/reports/basic', label: '基础报表', permissions: ['reports.view'] },
      { path: '/reports/exports', label: '报表导出', permissions: ['reports.view'] }
    ]
  },
  {
    label: '系统治理',
    children: [
      { path: '/settings/config-center', label: '配置中心', permissions: ['config.view'] },
      { path: '/settings/config-versions', label: '配置版本', permissions: ['config.view'] },
      { path: '/settings/platform-readiness', label: '平台准入', permissions: ['integrations.view'] },
      { path: '/audit/operations', label: '日志审计', internal: true }
    ]
  }
];

// Every authenticated route must be registered here. The guard deliberately
// denies paths without a contract so a newly added page cannot bypass RBAC.
export const routeCapabilities = [
  { path: '/', exact: true, userTypes: ['internal', 'external'] },
  { path: '/forbidden', exact: true },
  { path: '/analytics/sales', permissions: ['analytics.view'], userTypes: ['internal'] },
  { path: '/analytics/inventory', permissions: ['analytics.view'], userTypes: ['internal'] },
  { path: '/inventory/alerts', permissions: ['alerts.view'], userTypes: ['internal'] },
  { path: '/inventory/replenishment', permissions: ['replenishment.view'], userTypes: ['internal'] },
  { path: '/lifecycle/reviews', permissions: ['products.lifecycle.view'], userTypes: ['internal'] },
  { path: '/lifecycle/history', permissions: ['products.lifecycle.view'], userTypes: ['internal'] },
  { path: '/alerts/business', permissions: ['alerts.view'], userTypes: ['internal'] },
  { path: '/products/research', userTypes: ['internal'] },
  { path: '/products/master', userTypes: ['internal'] },
  { path: '/products/status-dashboard', permissions: ['products.status.view'], userTypes: ['internal'] },
  { path: '/products/status-recommendations', permissions: ['products.status.view'], userTypes: ['internal'] },
  { path: '/products/status-transitions', permissions: ['products.status.view'], userTypes: ['internal'] },
  { path: '/products/status', userTypes: ['internal'] },
  { path: '/purchasing/orders', userTypes: ['internal'] },
  { path: '/suppliers/my-performance', userTypes: ['external'] },
  { path: '/suppliers/performance', permissions: ['suppliers.performance.view'], userTypes: ['internal'] },
  { path: '/suppliers/tasks', userTypes: ['external'] },
  { path: '/suppliers/shipments', userTypes: ['external'] },
  { path: '/listings/sites', userTypes: ['internal'] },
  { path: '/listings/templates', userTypes: ['internal'] },
  { path: '/pricing/prices', userTypes: ['internal'] },
  { path: '/rpa/tasks', userTypes: ['internal'] },
  { path: '/rpa/stability', userTypes: ['internal'] },
  { path: '/rpa/attempts', userTypes: ['internal'] },
  { path: '/rpa/manual-queue', userTypes: ['internal'] },
  { path: '/rpa/account-locks', userTypes: ['internal'] },
  { path: '/rpa/page-signatures', userTypes: ['internal'] },
  { path: '/integrations/configs', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/integrations/sync-jobs', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/integrations/sync-runs', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/integrations/api-sync', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/finance/imports', permissions: ['finance.import'], userTypes: ['internal'] },
  { path: '/finance/statements', permissions: ['finance.view'], userTypes: ['internal'] },
  { path: '/finance/withdrawals', permissions: ['finance.view'], userTypes: ['internal'] },
  { path: '/finance/bank-receipts', permissions: ['finance.view'], userTypes: ['internal'] },
  { path: '/finance/reconciliation/matches', permissions: ['finance.view'], userTypes: ['internal'] },
  { path: '/finance/reconciliation/exceptions', permissions: ['finance.view'], userTypes: ['internal'] },
  { path: '/finance/analytics', permissions: ['finance.view'], userTypes: ['internal'] },
  { path: '/reports/basic', permissions: ['reports.view'], userTypes: ['internal'] },
  { path: '/reports/exports', permissions: ['reports.view'], userTypes: ['internal'] },
  { path: '/settings/platform-risk', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/settings/platform-readiness', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/settings/security-review', permissions: ['integrations.view'], userTypes: ['internal'] },
  { path: '/settings/config-center', permissions: ['config.view'], userTypes: ['internal'] },
  { path: '/settings/config-versions', permissions: ['config.view'], userTypes: ['internal'] },
  { path: '/audit/operations', userTypes: ['internal'] }
];

function matchesPath(contract, path) {
  return contract.exact
    ? path === contract.path
    : path === contract.path || path.startsWith(`${contract.path}/`);
}

export function findRouteCapability(path) {
  return routeCapabilities
    .filter((contract) => matchesPath(contract, path))
    .sort((a, b) => b.path.length - a.path.length)[0] || null;
}

export function hasRouteCapability(path) {
  return Boolean(findRouteCapability(path));
}

function canAccessCapability(user, capability) {
  if (!user || !capability) return false;
  if (capability.userTypes?.length && !capability.userTypes.includes(user.user_type)) return false;
  if (capability.internal && user.user_type !== 'internal') return false;
  if (user.is_superuser) return true;
  if (!capability.permissions?.length) return true;
  const permissions = new Set(user.permissions || []);
  return capability.permissions.some((code) => permissions.has(code));
}

export function canAccessMenuItem(user, item) {
  return canAccessCapability(user, item);
}

export function filterMenuItems(user, items = menuItems) {
  return items.flatMap((item) => {
    if (item.children) {
      const children = filterMenuItems(user, item.children);
      return children.length && canAccessMenuItem(user, item) ? [{ ...item, children }] : [];
    }
    return canAccessMenuItem(user, item) ? [item] : [];
  });
}

export function findMenuLabel(path, items = menuItems) {
  for (const item of items) {
    if (item.path === path) return item.label;
    const childLabel = item.children ? findMenuLabel(path, item.children) : '';
    if (childLabel) return childLabel;
  }
  return '';
}

export function flattenMenuItems(items) {
  return items.flatMap((item) => (item.children ? flattenMenuItems(item.children) : [item]));
}

export function canAccessPath(user, path) {
  return canAccessCapability(user, findRouteCapability(path));
}
