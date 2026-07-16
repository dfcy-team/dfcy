export function resolveWorkspace(user) {
  if (user?.is_superuser) {
    return { key: 'system', title: '系统管理员工作台', subtitle: '关注系统配置、集成状态、安全边界和审计。' };
  }
  const permissions = new Set(user?.permissions || []);
  if ([...permissions].some((code) => code.startsWith('finance.'))) {
    return { key: 'finance', title: '财务工作台', subtitle: '关注账单、到账、对账差异和授权导出。' };
  }
  if ([...permissions].some((code) => code.startsWith('integrations.') || code.startsWith('config.'))) {
    return { key: 'technical', title: '技术与集成工作台', subtitle: '关注同步运行、配置版本、异常和平台准入。' };
  }
  if ([...permissions].some((code) => code.startsWith('analytics.') || code.startsWith('reports.'))) {
    return { key: 'management', title: '经营管理工作台', subtitle: '关注经营指标、异常、审批和数据质量。' };
  }
  return { key: 'operations', title: '业务协同工作台', subtitle: '关注商品、采购、供应商和任务执行。' };
}

export function summarizeDataScope(user) {
  if (user?.is_superuser) return '全部租户内数据';
  const scopes = user?.data_scope || [];
  if (!scopes.length) return '仅基础租户范围';
  return scopes.map((scope) => scope.scope_type).filter(Boolean).join('、');
}
