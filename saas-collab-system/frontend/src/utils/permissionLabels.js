// Permission codes are API values and must remain unchanged.  Labels are a
// separate presentation concern because older backend seed migrations stored
// English names.  Keep this map as the UI fallback when an API response has no
// localized name yet.
export const permissionNames = Object.freeze({
  'products.research.view': '查看商品调研',
  'products.research.manage': '管理商品调研',
  'products.master.view': '查看商品主数据',
  'products.master.manage': '管理商品主数据',
  'products.master.freeze': '冻结商品编码',
  'products.category.view': '查看商品分类',
  'products.category.manage': '维护商品分类',
  'products.color.view': '查看颜色字典',
  'products.color.manage': '维护颜色字典',
  'products.attribute.view': '查看商品属性',
  'products.attribute.manage': '维护商品属性',
  'products.specification.view': '查看商品规格',
  'products.specification.manage': '维护商品规格',
  'products.bundle.view': '查看组合商品',
  'products.bundle.manage': '维护组合商品',
  'purchasing.orders.view': '查看采购订单',
  'purchasing.orders.manage': '管理采购订单',
  'workflow.approvals.view': '查看审批流程',
  'workflow.approvals.submit': '提交审批流程',
  'workflow.approvals.review': '审核审批流程',
  'workflow.approvals.withdraw': '撤回审批流程',
  'workflow.exceptions.view': '查看流程异常',
  'workflow.exceptions.manage': '处理流程异常',
  'workflow.collaboration.view': '查看协同反馈',
  'workflow.collaboration.confirm': '确认协同反馈',
  'rpa.tasks.view': '查看 RPA 任务',
  'rpa.tasks.manage': '管理 RPA 任务',
  'rpa.devices.view': '查看 RPA 设备',
  'rpa.devices.dry_run': '执行 RPA 演练',
  'rpa.stability.view': '查看 RPA 稳定性',
  'reports.view': '查看报表目录',
  'reports.export': '导出报表',
  'reports.download': '下载报表',
  'config.view': '查看系统配置',
  'config.manage': '管理系统配置',
  'config.approve': '审批系统配置',
  'config.rollback': '回滚系统配置',
  'config.system.manage': '管理系统级配置',
  'products.lifecycle.view': '查看商品生命周期',
  'products.lifecycle.evaluate': '评估商品生命周期',
  'products.lifecycle.confirm': '确认商品生命周期',
  'products.lifecycle.high_risk_confirm': '确认高风险生命周期',
  'replenishment.view': '查看补货建议',
  'replenishment.evaluate': '评估补货建议',
  'replenishment.review': '审核补货建议',
  'alerts.view': '查看运营预警',
  'alerts.evaluate': '评估运营预警',
  'alerts.manage': '管理运营预警',
  'analytics.view': '查看分析数据',
  'analytics.calculate': '计算分析数据',
  'analytics.manage': '管理分析定义',
  'finance.view': '查看财务数据',
  'finance.export': '导出财务数据',
  'finance.import': '导入财务数据',
  'finance.reconcile': '对账财务数据',
  'finance.exception.handle': '处理财务异常',
  'integrations.view': '查看集成配置',
  'integrations.manage': '管理集成配置',
  'integrations.rotate': '轮换集成凭据',
  'integrations.run': '运行集成同步',
  'suppliers.performance.view': '查看供应商绩效',
  'suppliers.performance.calculate': '计算供应商绩效',
  'products.status.view': '查看商品状态',
  'products.status.evaluate': '评估商品状态',
  'products.status.confirm': '确认商品状态',
  'products.status.high_risk_confirm': '确认高风险商品状态',
  'system.organization.view': '查看组织架构',
  'system.organization.manage': '管理组织架构',
  'system.users.view': '查看用户目录',
  'system.users.manage': '管理用户目录',
  'system.roles.view': '查看角色与权限',
  'system.roles.manage': '管理角色与权限',
  'masterdata.view': '查看基础档案',
  'masterdata.manage': '管理基础档案',
  'influencers.view': '查看达人目录',
  'influencers.manage': '管理达人目录',
  'influencers.outreach.view': '查看达人触达任务',
  'influencers.outreach.manage': '管理达人触达任务',
  'influencers.fulfillment.view': '查看样品履约',
  'influencers.fulfillment.manage': '管理样品履约',
  'influencers.catalog.view': '查看达人商品价格',
  'security.operations.view': '查看安全运维',
  'governance.api.view': '查看 API 合同',
  'governance.api.check': '检查 API 合同',
  'governance.assistants.view': '查看助手治理',
  'governance.assistants.evaluate': '评估助手定义',
  'pilot.readiness.view': '查看试点就绪度',
  'pilot.topology.view': '查看试点拓扑',
  'pilot.topology.verify': '验证试点拓扑',
  'pilot.recovery.view': '查看恢复计划',
  'pilot.recovery.plan': '规划恢复演练',
  'pilot.recovery.review': '审核恢复计划',
  'pilot.recovery.record': '记录恢复证据',
  'pilot.release.view': '查看发布计划',
  'pilot.release.plan': '规划试点发布',
  'pilot.release.review': '审核试点发布',
  'pilot.release.record': '记录发布证据',
  'pilot.release.rollback': '审核并记录回滚',
  'pilot.capacity.view': '查看试点容量',
  'pilot.control.view': '查看试点控制台',
  'pilot.security_review.view': '查看试点安全评审',
  'pilot.security_review.plan': '规划试点安全评审',
  'pilot.security_review.review': '审核试点安全评审',
  'listings.workbench.view': '查看全球刊登工作台',
  'listings.workbench.manage': '管理全球刊登工作台',
  'listings.mapping.view': '查看平台类目与属性映射',
  'listings.mapping.manage': '维护平台类目与属性映射',
  'listings.task.view': '查看刊登任务与日志',
  'listings.task.manage': '管理刊登任务',
  'listings.publish.production': '确认生产刊登'
});

const moduleNames = {
  products: '商品', purchasing: '采购', workflow: '流程', rpa: 'RPA', reports: '报表', config: '配置',
  replenishment: '补货', alerts: '预警', analytics: '分析', finance: '财务', integrations: '集成',
  suppliers: '供应商', system: '系统', masterdata: '基础档案', influencers: '达人', security: '安全',
  governance: '治理', pilot: '试点', listings: '刊登'
};
const actionNames = {
  view: '查看', manage: '管理', create: '创建', update: '更新', calculate: '计算', evaluate: '评估',
  review: '审核', confirm: '确认', submit: '提交', withdraw: '撤回', export: '导出', import: '导入',
  download: '下载', run: '运行', plan: '规划', record: '记录', verify: '验证', cancel: '取消',
  rollback: '回滚', rotate: '轮换', freeze: '冻结', handle: '处理', dry_run: '执行演练'
};
const resourceNames = {
  research: '商品调研', master: '商品主数据', orders: '采购订单', approvals: '审批流程', exceptions: '流程异常',
  collaboration: '协同反馈', tasks: '任务', devices: '设备', stability: '稳定性', roles: '角色与权限',
  users: '用户目录', organization: '组织架构', readiness: '试点就绪度', topology: '试点拓扑', recovery: '恢复计划',
  release: '试点发布', capacity: '试点容量', control: '试点控制台', security_review: '试点安全评审',
  verification: '验证运行', performance: '性能运行', entry: '准入决策'
};

const hasChinese = (value) => /[\u4e00-\u9fff]/u.test(String(value || ''));

function genericPermissionLabel(code) {
  const parts = String(code || '').split('.');
  const actionPart = parts[parts.length - 1];
  const resourcePart = parts[parts.length - 2];
  const action = actionNames[actionPart] || '配置';
  const resource = resourceNames[resourcePart] || resourcePart?.replaceAll('_', ' ');
  const module = moduleNames[parts[0]] || parts[0];
  return resource ? `${action}${resource}` : `${action}${module || '权限'}`;
}

export function permissionLabel(permission) {
  const code = typeof permission === 'string' ? permission : permission?.code;
  const name = typeof permission === 'string' ? '' : permission?.name_zh || permission?.name;
  if (permissionNames[code]) return permissionNames[code];
  if (hasChinese(name)) return name;
  return genericPermissionLabel(code);
}

export function permissionModuleLabel(module) {
  return moduleNames[module] || module || '权限';
}
