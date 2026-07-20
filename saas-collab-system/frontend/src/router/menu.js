export const menuItems = [
  { path: '/', label: '工作台' },
  {
    label: '经营分析',
    permissions: ['analytics.view'],
    children: [
      { path: '/analytics/overview', label: '经营总览', permissions: ['analytics.view'] },
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
      { path: '/lifecycle/clearance-requests', label: '清仓申请', permissions: ['workflow.approvals.view'] },
      { path: '/alerts/business', label: '经营预警', permissions: ['alerts.view'] }
    ]
  },
  {
    label: '流程协同',
    children: [
      { path: '/workflow/approvals', label: '审批中心', permissions: ['workflow.approvals.view'] },
      { path: '/workflow/exceptions', label: '异常中心', permissions: ['workflow.exceptions.view'] },
      { path: '/workflow/collaboration-events', label: '协同回填', permissions: ['workflow.collaboration.view'] }
    ]
  },
  {
    label: '业务协同',
    internal: true,
    children: [
      { path: '/products/research', label: '新品市调', permissions: ['products.research.view'] },
      { path: '/products/master', label: '商品主数据', permissions: ['products.master.view'] },
      { path: '/purchasing/orders', label: '采购订单', permissions: ['purchasing.orders.view'] },
      { path: '/suppliers/performance', label: '供应商绩效', permissions: ['suppliers.performance.view'] },
      { path: '/listings/sites', label: '多国家刊登', internal: true },
      { path: '/pricing/prices', label: '价格中心', internal: true }
    ]
  },
  {
    label: 'RPA协同',
    internal: true,
    children: [
      { path: '/rpa/tasks', label: '任务中心', permissions: ['rpa.tasks.view'] },
      { path: '/rpa/runs', label: '运行记录', permissions: ['rpa.tasks.view'] },
      { path: '/rpa/devices', label: '设备管理', permissions: ['rpa.devices.view'] },
      { path: '/rpa/manual-queue', label: '人工队列', permissions: ['rpa.tasks.view'] },
      { path: '/rpa/stability', label: '稳定性', permissions: ['rpa.stability.view'] },
      { path: '/rpa/account-locks', label: '账号串行锁', permissions: ['rpa.stability.view'] },
      { path: '/rpa/page-signatures', label: '页面签名', permissions: ['rpa.stability.view'] }
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
    label: '基础档案',
    permissions: ['masterdata.view'],
    children: [
      { path: '/master-data/platforms', label: '平台档案', permissions: ['masterdata.view'] },
      { path: '/master-data/stores', label: '店铺档案', permissions: ['masterdata.view'] },
      { path: '/master-data/warehouses', label: '仓库档案', permissions: ['masterdata.view'] },
      { path: '/master-data/suppliers', label: '供应商档案', permissions: ['masterdata.view'] }
    ]
  },
  {
    label: '系统治理',
    children: [
      { path: '/system/departments', label: '组织架构', permissions: ['system.organization.view'] },
      { path: '/system/users', label: '用户目录', permissions: ['system.users.view'] },
      { path: '/system/roles', label: '角色权限', permissions: ['system.roles.view'] },
      { path: '/system/security-operations', label: '安全运维', permissions: ['security.operations.view'] },
      { path: '/settings/config-center', label: '配置中心', permissions: ['config.view'] },
      { path: '/settings/config-versions', label: '配置版本', permissions: ['config.view'] },
      { path: '/settings/platform-readiness', label: '平台准入', permissions: ['integrations.view'] },
      { path: '/audit/operations', label: '日志审计', internal: true }
    ]
  },
  {
    label: '治理与试点',
    children: [
      { path: '/governance/api-contracts', label: 'API 合同', permissions: ['governance.api.view'] },
      { path: '/governance/assistants', label: '助手治理', permissions: ['governance.assistants.view'] },
      { path: '/pilot/readiness', label: '试点准入', permissions: ['pilot.readiness.view'] },
      { path: '/pilot/topology', label: '部署拓扑', permissions: ['pilot.topology.view'] },
      { path: '/pilot/recovery', label: '恢复演练', permissions: ['pilot.recovery.view'] },
      { path: '/pilot/releases', label: '发布记录', permissions: ['pilot.release.view'] },
      { path: '/pilot/capacity', label: '容量观察', permissions: ['pilot.capacity.view'] }
    ]
  }
];

// Every authenticated route must be registered here. The guard deliberately
// denies paths without a contract so a newly added page cannot bypass RBAC.
export const routeCapabilities = [
  { path: '/', exact: true, userTypes: ['internal', 'external'] },
  { path: '/forbidden', exact: true },
  { path: '/analytics/overview', permissions: ['analytics.view'], userTypes: ['internal'] },
  { path: '/analytics/sales', permissions: ['analytics.view'], userTypes: ['internal'] },
  { path: '/analytics/inventory', permissions: ['analytics.view'], userTypes: ['internal'] },
  { path: '/inventory/alerts', permissions: ['alerts.view'], userTypes: ['internal'] },
  { path: '/inventory/replenishment', permissions: ['replenishment.view'], userTypes: ['internal'] },
  { path: '/lifecycle/reviews', permissions: ['products.lifecycle.view'], userTypes: ['internal'] },
  { path: '/lifecycle/history', permissions: ['products.lifecycle.view'], userTypes: ['internal'] },
  { path: '/lifecycle/clearance-requests', permissions: ['workflow.approvals.view'], userTypes: ['internal'] },
  { path: '/alerts/business', permissions: ['alerts.view'], userTypes: ['internal'] },
  { path: '/workflow/approvals', permissions: ['workflow.approvals.view'], userTypes: ['internal'] },
  { path: '/workflow/exceptions', permissions: ['workflow.exceptions.view'], userTypes: ['internal'] },
  { path: '/workflow/collaboration-events', permissions: ['workflow.collaboration.view'], userTypes: ['internal'] },
  { path: '/products/research', permissions: ['products.research.view'], userTypes: ['internal'] },
  { path: '/products/master', permissions: ['products.master.view'], userTypes: ['internal'] },
  { path: '/products/status-dashboard', permissions: ['products.status.view'], userTypes: ['internal'] },
  { path: '/products/status-recommendations', permissions: ['products.status.view'], userTypes: ['internal'] },
  { path: '/products/status-transitions', permissions: ['products.status.view'], userTypes: ['internal'] },
  { path: '/products/status', permissions: ['products.master.view'], userTypes: ['internal'] },
  { path: '/purchasing/orders', permissions: ['purchasing.orders.view'], userTypes: ['internal'] },
  { path: '/suppliers/my-performance', userTypes: ['external'] },
  { path: '/suppliers/performance', permissions: ['suppliers.performance.view'], userTypes: ['internal'] },
  { path: '/suppliers/tasks', userTypes: ['external'] },
  { path: '/suppliers/shipments', userTypes: ['external'] },
  { path: '/listings/sites', userTypes: ['internal'] },
  { path: '/listings/templates', userTypes: ['internal'] },
  { path: '/pricing/prices', userTypes: ['internal'] },
  { path: '/rpa/tasks', permissions: ['rpa.tasks.view'], userTypes: ['internal'] },
  { path: '/rpa/runs', permissions: ['rpa.tasks.view'], userTypes: ['internal'] },
  { path: '/rpa/attempts', permissions: ['rpa.tasks.view'], userTypes: ['internal'] },
  { path: '/rpa/devices', permissions: ['rpa.devices.view'], userTypes: ['internal'] },
  { path: '/rpa/manual-queue', permissions: ['rpa.tasks.view'], userTypes: ['internal'] },
  { path: '/rpa/stability', permissions: ['rpa.stability.view'], userTypes: ['internal'] },
  { path: '/rpa/account-locks', permissions: ['rpa.stability.view'], userTypes: ['internal'] },
  { path: '/rpa/page-signatures', permissions: ['rpa.stability.view'], userTypes: ['internal'] },
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
  { path: '/system/departments', permissions: ['system.organization.view'], userTypes: ['internal'] },
  { path: '/system/users', permissions: ['system.users.view'], userTypes: ['internal'] },
  { path: '/system/roles', permissions: ['system.roles.view'], userTypes: ['internal'] },
  { path: '/system/security-operations', permissions: ['security.operations.view'], userTypes: ['internal'] },
  { path: '/master-data/platforms', permissions: ['masterdata.view'], userTypes: ['internal'] },
  { path: '/master-data/stores', permissions: ['masterdata.view'], userTypes: ['internal'] },
  { path: '/master-data/warehouses', permissions: ['masterdata.view'], userTypes: ['internal'] },
  { path: '/master-data/suppliers', permissions: ['masterdata.view'], userTypes: ['internal'] },
  { path: '/audit/operations', userTypes: ['internal'] },
  { path: '/governance/api-contracts', permissions: ['governance.api.view'], userTypes: ['internal'] },
  { path: '/governance/assistants', permissions: ['governance.assistants.view'], userTypes: ['internal'] },
  { path: '/pilot/readiness', permissions: ['pilot.readiness.view'], userTypes: ['internal'] },
  { path: '/pilot/topology', permissions: ['pilot.topology.view'], userTypes: ['internal'] },
  { path: '/pilot/recovery', permissions: ['pilot.recovery.view'], userTypes: ['internal'] },
  { path: '/pilot/releases', permissions: ['pilot.release.view'], userTypes: ['internal'] },
  { path: '/pilot/capacity', permissions: ['pilot.capacity.view'], userTypes: ['internal'] }
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
