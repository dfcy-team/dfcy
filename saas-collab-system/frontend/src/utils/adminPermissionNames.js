import { permissionNames } from './permissionLabels';

const words = Object.freeze({
  alerts: '运营预警', analytics: '经营分析', audit: '操作审计', config: '系统配置', development: '产品开发',
  finance: '财务管理', governance: '平台治理', influencers: '达人运营', integrations: '数据接入', listings: '商品刊登',
  masterdata: '基础档案', pilot: '试点管理', products: '商品管理', purchasing: '采购管理', release: '发布管理',
  replenishment: '补货管理', reports: '报表中心', rpa: '自动化协同', sales: '销售管理', sales_management: '销售管理',
  security: '安全运维', suppliers: '供应商管理', supply: '供应链协同', system: '系统管理', workflow: '流程协同',
  research: '商品调研', master: '商品主数据', category: '商品分类', color: '颜色字典', attribute: '商品属性',
  specification: '商品规格', bundle: '组合商品', orders: '采购订单', approvals: '审批流程', exceptions: '流程异常',
  collaboration: '协同反馈', tasks: '任务', task: '任务', devices: '自动化设备', stability: '稳定性', roles: '角色与权限',
  users: '用户目录', organization: '组织架构', readiness: '试点就绪度', topology: '试点拓扑', recovery: '恢复计划',
  capacity: '试点容量', control: '试点控制台', security_review: '安全评审', release: '发布计划', performance: '性能运行',
  api: '接口', assistants: '助手治理', store: '店铺', store_mapping: '店铺平台关联', product_mapping: '商品映射',
  warehouse: '仓库', credential: '平台凭据', mapping: '平台映射', product_detail: '平台商品明细', workbench: '刊登工作台',
  publish: '商品刊登', lifecycle: '商品生命周期', status: '商品状态', performance: '供应商绩效', fulfillment: '样品履约',
  outreach: '达人触达', catalog: '达人商品目录', operation_logs: '操作审计日志', entry: '准入决策', verification: '验证运行',
  product_archive: '产品档案', production: '生产操作', system: '系统', tenants: '租户目录', tenant: '租户',
  view: '查看', manage: '管理', create: '创建', update: '更新', calculate: '计算', evaluate: '评估', review: '审核',
  confirm: '确认', submit: '提交', withdraw: '撤回', export: '导出', import: '导入', download: '下载', run: '运行',
  plan: '规划', record: '记录', verify: '验证', cancel: '取消', rollback: '回滚', execute: '执行', rotate: '轮换',
  freeze: '冻结', handle: '处理', dry_run: '演练', reconcile: '对账', restore: '恢复', revoke: '撤销', sync: '同步',
  retry: '重试', authorize: '授权', clear: '清理', disable: '停用', approve: '审批', check: '检查', production: '生产操作',
  run_live_readonly: '生产只读检查', high_risk_confirm: '高风险确认', color_code: '颜色编码', id: '编号', image_url: '图片地址',
  is_active: '启用状态', legacy_sku_code: '旧版 SKU 编码', material: '材质', product_name: '商品名称', size: '尺寸',
  sku_code: 'SKU 编码', specification: '规格', spu_id: 'SPU 编号', updated_at: '更新时间', brand: '品牌',
  legacy_spu_code: '旧版 SPU 编码', lifecycle_status: '生命周期状态', sales_status: '销售状态', spu_code: 'SPU 编码',
  code: '编码', country_code: '国家编码', currency: '币种', name: '名称', platform_id: '平台编号', platform_site_id: '站点编号',
  warehouse_type: '仓库类型', department: '所属部门', full_name: '姓名',
  cost: '成本', costs: '成本', projects: '开发项目', requirements: '需求', dashboard: '业务看板', overview: '总览',
  advertising: '广告', sales: '销售', inventory: '库存', data_quality: '数据质量', orders: '订单', returns: '退货',
  exports: '导出任务', imports: '导入任务', reconciliation: '财务对账', statements: '财务报表', bank_receipts: '银行收款',
  withdrawals: '提现', reconciliation_exceptions: '对账异常', reconciliation_matches: '对账匹配', performance: '绩效',
  outreach_tasks: '达人触达任务', sample_fulfillments: '样品履约', configs: '配置', incidents: '故障事件', sync_jobs: '同步任务',
  sync_runs: '同步运行记录', platform_sites: '平台站点', platform_drill: '平台联调', capabilities: '功能能力',
  production_settings: '生产环境设置', readiness: '就绪状态', internal_api_client: '内部接口客户端', open_api: '开放接口',
  feishu: '飞书', settings: '设置', config_center: '配置中心', config_versions: '配置版本', module_controls: '模块控制',
  platform_readiness: '平台就绪状态', categories: '商品分类', attributes: '商品属性', colors: '颜色字典', details: '商品明细',
  specifications: '商品规格', platforms: '平台', sites: '站点', stores: '店铺', suppliers: '供应商', warehouses: '仓库',
  online_products: '在线商品', attribute_mappings: '属性映射', category_mappings: '类目映射', exceptions: '异常记录',
  logs: '操作日志', tasks: '任务', templates: '模板', contracts: '接口合同', releases: '发布记录', validation: '验证',
  control_room: '控制室', manual_queue: '人工队列', account_locks: '账号锁定', page_signatures: '页面特征', runs: '运行记录',
  consolidation: '合并作业', consolidations: '合并作业', consolidation_site: '合并站点', shipments: '发货', shipment: '发货单',
  packing: '打包', customs: '海关', clearance: '清关', route: '路线', shipping_route: '物流路线', arrival: '到货',
  warehouse_arrival: '仓库到货', port_arrival: '港口到货', receive: '收货', dispatch: '派发', transfer: '调拨',
  purchase_order: '采购订单', decision_alerts_business: '预警业务决策', decision_inventory_alerts: '库存预警决策',
  decision_inventory_replenishment: '库存补货决策', decision_lifecycle_clearance_requests: '生命周期清仓申请决策',
  decision_lifecycle_history: '生命周期历史决策', decision_lifecycle_reviews: '生命周期审核决策',
  analytics_advertising_overview: '广告经营总览', analytics_advertising_performance: '广告经营绩效', analytics_inventory: '库存分析',
  analytics_overview: '经营总览', analytics_sales: '销售分析', finance_advertising_reconciliation: '广告费用对账', finance_analytics: '财务分析',
  influencers_bd_config: '达人商务配置', influencers_bd_performance: '达人商务绩效', influencers_outreach_tasks: '达人触达任务',
  influencers_sample_fulfillments: '达人样品履约', listings_exceptions: '刊登异常', listings_logs: '刊登日志',
  listings_online_products: '在线刊登商品', listings_sites: '刊登站点', listings_tasks: '刊登任务', listings_templates: '刊登模板',
  master_data_platforms: '平台档案', master_data_settings: '基础档案设置', master_data_sites: '站点档案', master_data_stores: '店铺档案',
  master_data_suppliers: '供应商档案', master_data_warehouses: '仓库档案', products_attributes: '商品属性', products_categories: '商品分类',
  products_colors: '商品颜色', products_details: '商品明细', products_master: '商品主数据', products_platform_details: '平台商品明细',
  products_research: '商品调研', products_specifications: '商品规格', products_costs: '商品成本', reports_basic: '基础报表',
  reports_exports: '报表导出', sales_management_data_quality: '销售数据质量', sales_management_exports: '销售数据导出',
  sales_management_orders: '销售订单', sales_management_overview: '销售经营总览', sales_management_returns: '销售退货',
  sales_management_skus: '销售商品编码', sales_management_stores: '销售店铺', security_operations: '安全运维',
  supply_chain_consolidations: '供应链合并作业', supply_chain_shipments: '供应链发货', settings_config_center: '配置中心',
  settings_config_versions: '配置版本', settings_module_controls: '模块控制', settings_platform_readiness: '平台就绪状态',
  workflow_approvals: '审批流程', workflow_collaboration_events: '协同事件', workflow_exceptions: '流程异常',
  accept: '受理', allocate: '分配', assign: '分配', change: '变更', complete: '完成', connection: '连接', contract: '接口合同',
  decision: '决策', exception: '异常', identity: '身份', menu: '菜单', notification: '通知', profile: '资料', project: '项目',
  requirement: '需求', sample: '样品', skus: '商品编码', start: '启动', template: '模板', country_code: '国家编码', currency: '币种',
  brand: '品牌', code: '编码', id: '编号', name: '名称', settings: '设置', is_active: '启用状态', updated_at: '更新时间',
  image_url: '图片地址', legacy_sku_code: '旧版商品编码', legacy_spu_code: '旧版商品主编码', lifecycle_status: '生命周期状态',
  sales_status: '销售状态', spu_code: '商品主编码', platform_id: '平台编号', platform_site_id: '站点编号',
});

const fieldResources = Object.freeze({ products: '商品', product_details: '商品明细', stores: '店铺', warehouses: '仓库', roles: '角色', tenants: '租户', users: '用户' });
const semanticLabels = Object.freeze({
  'feishu.view':'查看飞书协同', 'feishu.connection.manage':'管理飞书连接', 'feishu.identity.manage':'管理飞书身份', 'feishu.notification.manage':'管理飞书通知', 'feishu.report.manage':'管理飞书报表', 'feishu.approval.manage':'管理飞书审批', 'feishu.operations.view':'查看飞书运行记录', 'feishu.operations.retry':'重试飞书失败任务',
  'field.system.users.status.view':'查看用户账号状态字段', 'field.system.users.roles.view':'查看用户角色字段',
  'integrations.product_mapping.view':'查看商品编码映射', 'integrations.product_mapping.manage':'维护商品编码映射',
  'listings.profile.view':'查看刊登资料', 'listings.profile.manage':'维护刊登资料',
  'release.contract.view':'查看发布合同', 'release.contract.manage':'维护发布合同', 'release.contract.approve':'审批发布合同', 'release.contract.execute':'执行发布合同',
});
const chineseOnly = (value) => String(value).replace(/RPA/giu, '自动化').replace(/SKU\s*编码/giu, '商品编码').replace(/SKU/giu, '商品编码').replace(/SPU\s*编码/giu, '商品主编码').replace(/SPU/giu, '商品主编码').replace(/WMS/giu, '仓储系统').replace(/API/giu, '接口').replace(/\s+/gu, '');

export function adminPermissionLabel(permission) {
  const code = typeof permission === 'string' ? permission : permission?.code;
  const supplied = typeof permission === 'string' ? '' : (permission?.name_zh || permission?.name || '');
  if (supplied && /[\u4e00-\u9fff]/u.test(supplied) && !/[A-Za-z]/u.test(supplied)) return supplied;
  if (semanticLabels[code]) return semanticLabels[code];
  if (permissionNames[code]) return chineseOnly(permissionNames[code]);
  const parts = String(code || '').split('.').filter(Boolean);
  if (parts[0] === 'field' && parts.length >= 5) {
    const resource = fieldResources[parts.at(-3)] || '业务数据';
    const field = words[parts.at(-2)] || parts.at(-2).replaceAll('_', '');
    const operation = parts.at(-1) === 'view' ? '查看' : (words[parts.at(-1)] || '访问');
    return chineseOnly(`${operation}${resource}${field}字段`);
  }
  const action = words[parts.at(-1)] || '访问';
  const resourcePart = parts.length > 1 ? parts.at(-2) : '';
  const resource = words[resourcePart] || (resourcePart ? '相关业务' : '权限');
  const prefix = parts[0] === resourcePart ? '' : (words[parts[0]] || '');
  return chineseOnly(`${action}${prefix && !resource.startsWith(prefix) ? prefix : ''}${resource}`);
}

export const adminPermissionNames = permissionNames;
