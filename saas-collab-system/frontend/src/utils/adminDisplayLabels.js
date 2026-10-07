import { adminPermissionLabel as permissionDisplayLabel } from './adminPermissionNames';

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
  workflow: '流程协同', feishu: '飞书协同', inventory: '库存管理',
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
  return permissionDisplayLabel(permission);
}

const valueLabels = Object.freeze({ action: '操作权限', menu: '菜单权限', field: '字段权限', api: '接口权限',
  role: '角色继承', user: '用户指定', group: '用户组继承', system: '系统内置', active: '启用', inactive: '停用',
  pending: '待处理', approved: '已批准', rejected: '已拒绝', normal: '普通', high: '高风险', critical: '严重风险',
  tenant: '租户', organization: '组织', department: '部门', user_scope: '用户', store: '店铺', platform: '平台',
  reason: '原因未说明', unknown: '未知', position: '组织岗位', legacy: '旧版租户授权', direct: '直接授权',
  platform_ids: '平台', site_ids: '站点', store_ids: '店铺', warehouse_ids: '仓库', supplier_ids: '供应商',
  department_ids: '部门', user_ids: '用户', role_ids: '角色', });
export function adminPermissionTypeLabel(value) { return valueLabels[value] || '其他权限类型'; }
export function adminPermissionSourceLabel(value) { return valueLabels[value] || '其他来源'; }
export function adminStatusLabel(value) { return valueLabels[value] || '其他状态'; }
export function adminReasonLabel(value) { return value ? (valueLabels[value] || String(value).replaceAll('_', ' ')) : '原因未说明'; }
export function adminDimensionLabel(value) { return valueLabels[value] || '其他数据范围'; }

const builtInRoleLabels = Object.freeze({
  administrator: '租户管理员', operations: '业务运营人员', product_developer: '产品开发人员', '002': '达人运营管理员',
});

export function adminRoleDisplayName(role) {
  const rawName = departmentDisplayName(role?.name || '').trim();
  if (builtInRoleLabels[role?.code] && (!rawName || rawName === role.code)) return builtInRoleLabels[role.code];
  if (rawName) return rawName;
  if (builtInRoleLabels[role?.code]) return builtInRoleLabels[role.code];
  return role?.id ? `自定义角色${role.id}` : '未命名角色';
}

export function departmentDisplayName(name) {
  return String(name || '');
}

export function tenantDisplayName(tenant, fallback = '当前租户') {
  return tenant?.name || fallback;
}
