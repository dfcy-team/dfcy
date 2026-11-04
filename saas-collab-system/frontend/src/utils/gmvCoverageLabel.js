// Ownership and expected days come from server-side platform ID evidence.
export function gmvCoverageLabel(item) {
  const c = item.api_coverage;
  const pending = { label: '待 API 关联核验', type: 'info', accountCount: null };
  if (item.conflict) return { ...pending, label: '快照冲突，金额不展示', type: 'danger' };
  if (!c || !Number.isInteger(c.expected_days) || c.expected_days <= 0
    || !Number.isInteger(c.stored_days) || c.stored_days < 0 || c.stored_days > c.expected_days
    || !Number.isInteger(c.account_count)) return pending;
  const ratio = `${c.stored_days}/${c.expected_days} 广告户日`;
  if (c.unverified_report_days) return { label: `历史报表关联待核验 · ${ratio}`, type: 'warning', accountCount: c.account_count };
  const complete = c.complete === true && c.stored_days === c.expected_days;
  return { label: complete ? `所选范围已覆盖 · ${ratio}` : `缺 ${c.expected_days - c.stored_days} 个广告户日 · ${ratio}`,
    type: complete ? 'success' : 'warning', accountCount: c.account_count };
}
