const commonAccess = [
  '广告账户授权',
  '将广告账户映射到现有租户、平台和店铺',
  '提供日粒度报表及覆盖范围，并明确归因窗口、时区和币种',
  '建立计划与 SKU 映射，并配置用户权限和数据范围'
];

export const advertisingReportPlans = {
  overview: {
    title: '广告总览',
    description: '按日期、平台、店铺和账户汇总投放规模与归因效果。',
    metrics: ['曝光', '点击', '消耗', '归因订单', '归因销售额', 'CTR', 'CPC', 'CVR', 'CPA', 'ROAS', 'ACOS'],
    dimensions: ['日期', '平台', '店铺', '广告账户'],
    access: commonAccess
  },
  performance: {
    title: '广告投放分析',
    description: '逐层查看投放对象、商品和素材表现；关键词或搜索词仅在平台提供时展示。',
    metrics: ['曝光', '点击', '消耗', '归因订单', '归因销售额', 'CTR', 'CPC', 'CVR', 'CPA', 'ROAS', 'ACOS'],
    dimensions: ['账户', '计划', '广告组', '广告', '商品 SKU', '素材', '关键词或搜索词（平台提供时）'],
    access: [...commonAccess, '确认计划、广告组、素材及商品 SKU 的平台映射']
  },
  reconciliation: {
    title: '广告费用对账',
    description: '按账户、结算周期和币种对应广告消耗、平台账单与财务记录。',
    metrics: ['广告报表消耗', '账单扣费', '退款或调整', '税费', '财务入账', '消耗与账单差额', '账单与入账差额'],
    dimensions: ['广告账户', '结算周期', '币种'],
    access: [...commonAccess, '提供平台账单及其与财务入账的对应关系', '同一周期金额先统一税费和调整规则']
  }
};

export const advertisingMetricDefinitions = [
  ['CTR', '点击 ÷ 曝光 × 100%'],
  ['CPC', '消耗 ÷ 点击'],
  ['CVR', '平台定义的归因转化数 ÷ 点击 × 100%'],
  ['CPA', '消耗 ÷ 同口径归因转化数'],
  ['ROAS', '归因销售额 ÷ 消耗'],
  ['ACOS', '消耗 ÷ 归因销售额 × 100%']
];

export const advertisingReconciliationDefinitions = [
  ['消耗与账单差额', '同一账户、结算周期和币种的报表消耗，减去已对齐税费、退款和调整口径的账单扣费。'],
  ['账单与入账差额', '已对齐口径的账单扣费，减去对应财务入账；税费、退款和调整分别保留核对依据。'],
  ['时间差及未匹配', '跨期、未匹配和缺少来源的项目单列；缺少账单或财务流水时显示未覆盖，不判定为零差异。']
];
