// Coverage belongs to this report's accounts, not all historical store mappings.
export function gmvCoverageLabel(item, report) {
  const start = Date.parse(report.date_from);
  const end = Date.parse(report.date_to);
  const accountCount = item.advertiser_id ? 1 : item.advertiser_count;
  const days = Number.isFinite(start) && Number.isFinite(end)
    ? Math.floor((end - start) / 86400000) + 1
    : item.expected_days / (accountCount || 1);
  const allowed = new Set((report.selected_subjects || []).filter(s => s.store_code === item.store_code
    && s.historical_binding_confirmed).map(s => s.advertiser_id));
  const rows = (report.gmv_max_snapshots || []).filter(r => r.store_code === item.store_code
    && r.currency === item.currency && r.timezone === item.timezone
    && r.platform_store_id === item.platform_store_id
    && (item.advertiser_id ? r.advertiser_id === item.advertiser_id : allowed.has(r.advertiser_id))
    && (!Number.isFinite(start) || Date.parse(r.date) >= start)
    && (!Number.isFinite(end) || Date.parse(r.date) <= end));
  const verified = new Set(rows.map(r => r.advertiser_id));
  const withData = new Set(rows.filter(r => r.collection_status !== 'no_data').map(r => r.advertiser_id));
  const covered = new Set(rows.map(r => `${r.advertiser_id}/${r.date}`)).size;
  const expected = verified.size * days;
  const missing = Math.max(0, expected - covered);
  let label = '暂无可核验的日报';
  if (verified.size) {
    label = missing ? `缺 ${missing} 个广告户日 · ${covered}/${expected} 广告户日`
      : `所选范围已覆盖 · ${covered}/${expected} 广告户日`;
  }
  return { label: item.conflict ? '快照冲突，金额不展示' : label,
    type: item.conflict ? 'danger' : missing ? 'warning' : verified.size ? 'success' : 'info',
    dataAccounts: withData.size, accountCount: verified.size,
  };
}
