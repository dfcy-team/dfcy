export function dateFilters(range, status, allHistory = false) {
  return {
    created_after: range?.[0] ? `${range[0]}T00:00:00+08:00` : undefined,
    created_before: range?.[1] ? `${range[1]}T23:59:59.999999+08:00` : undefined,
    all_history: status === 'closed' && (allHistory || Boolean(range)) ? 'true' : undefined,
    closed_after: status === 'closed' && !range && !allHistory ? new Date(Date.now() - 30 * 86400000).toISOString() : undefined,
  };
}
