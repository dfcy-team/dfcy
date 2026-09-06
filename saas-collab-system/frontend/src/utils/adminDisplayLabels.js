import { permissionLabel } from './permissionLabels';

// API values stay in English because they are stable contracts.  These labels
// are only for the administration UI and intentionally fail closed to simple
// Chinese wording instead of leaking an unknown code to an operator.
export const adminModuleLabels = Object.freeze({
  alerts: '运营预警', analytics: '经营分析', audit: '操作审计', config: '系统配置',
  development: '产品开发', finance: '财务管理', governance: '平台治理', influencers: '达人运营',
  integrations: '数据接入', listings: '商品刊登', masterdata: '基础档案', pilot: '试点管理',
  products: '商品管理', purchasing: '采购管理', release: '发布管理', replenishment: '补货管理',
  reports: '报表中心', rpa: '自动化协同', sales: '销售管理', sales_management: '销售管理',
  security: '安全运维', suppliers: '供应商管理', supply: '供应链协同', system: '系统管理',
  workflow: '流程协同',
});

const adminActionLabels = Object.freeze({
  api: '接口', calculate: '计算', cancel: '取消', confirm: '确认', create: '创建', disable: '停用',
  download: '下载', dry_run: '演练', evaluate: '评估', execute: '执行', export: '导出', freeze: '冻结',
  handle: '处理', import: '导入', manage: '管理', plan: '规划', record: '记录', reconcile: '对账',
  restore: '恢复', review: '审核', revoke: '撤销', rollback: '回滚', rotate: '轮换', run: '运行',
  submit: '提交', sync: '同步', update: '更新', verify: '验证', view: '查看', withdraw: '撤回',
  production: '生产操作', run_live_readonly: '生产只读检查',
});

const adminResourceLabels = Object.freeze({
  api: '接口', approvals: '审批流程', assistants: '助手治理', attribute: '商品属性', bundle: '组合商品',
  capacity: '试点容量', category: '商品分类', collaboration: '协同反馈', config: '配置', control: '控制台',
  credential: '凭据', devices: '自动化设备', entry: '准入决策', exceptions: '流程异常', fulfillment: '样品履约',
  lifecycle: '商品生命周期', mapping: '平台映射', master: '商品主数据', operation_logs: '操作审计日志',
  orders: '采购订单', organization: '组织架构', performance: '性能运行', product_archive: '产品档案',
  product_detail: '商品明细', product_mapping: '商品映射', production: '生产操作', readiness: '试点就绪度',
  recovery: '恢复计划', release: '发布计划', research: '商品调研', roles: '角色权限', security_review: '安全评审',
  stability: '稳定性', store: '店铺', store_mapping: '店铺映射', task: '任务', tasks: '任务', topology: '拓扑',
  users: '用户目录', verification: '验证运行', warehouse: '仓库',
});

const hasChinese = (value) => /[\u4e00-\u9fff]/u.test(String(value || ''));
const hasLatin = (value) => /[A-Za-z]/u.test(String(value || ''));

export function adminModuleLabel(module) {
  return adminModuleLabels[String(module || '').trim().toLowerCase()] || '其他模块';
}

export function adminPermissionLabel(permission) {
  const code = typeof permission === 'string' ? permission : permission?.code;
  const name = typeof permission === 'string' ? '' : (permission?.name_zh || permission?.name || '');
  if (hasChinese(name) && !hasLatin(name)) return name;
  const localized = permissionLabel(permission);
  if (hasChinese(localized) && !hasLatin(localized)) return localized;
  const parts = String(code || '').split('.').filter(Boolean);
  const action = adminActionLabels[parts.at(-1)] || '配置';
  const resource = adminResourceLabels[parts.at(-2)] || '';
  return resource ? `${action}${resource}` : `${action}权限`;
}

const builtInRoleLabels = Object.freeze({
  administrator: '租户管理员', operations: '业务运营人员', product_developer: '产品开发人员', '002': '达人运营管理员',
});

export function adminRoleDisplayName(role) {
  if (builtInRoleLabels[role?.code]) return builtInRoleLabels[role.code];
  const rawName = departmentDisplayName(role?.name || '')
    .replace(/pilot\s+e2e\s+admin/gi, '试点管理员')
    .replace(/pilot\s+e2e\s+scoped/gi, '试点范围角色')
    .replace(/^bd$/i, '商务拓展').trim();
  if (rawName && !hasLatin(rawName)) return rawName;
  return role?.id ? `自定义角色${role.id}` : '未命名角色';
}

export function departmentDisplayName(name) {
  return String(name || '').replace(/shopee/gi, '虾皮').replace(/tiktok/gi, '短视频');
}

export function tenantDisplayName(tenant, fallback = '当前租户') {
  return tenant?.name || fallback;
}
