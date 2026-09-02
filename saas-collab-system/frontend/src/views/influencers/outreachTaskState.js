const hasValue = (value) => value !== undefined && value !== null && value !== '';

export function completedFulfillmentCount(row = {}) {
  return Number(row?.sample_fulfillment_completed_count ?? row?.completion_validation?.completed_count ?? 0);
}

export function fulfillmentCount(row = {}) {
  return Number(row?.sample_fulfillment_count ?? row?.sample_status_summary?.total ?? 0);
}

export function sampleProgressLabel(row = {}) {
  const targetCount = row?.target_count;
  const display = (value) => hasValue(value) ? String(value) : '—';
  return `${display(fulfillmentCount(row))}/${display(targetCount)}`;
}
export function outreachProgressLabel(detailProgress, detailTask) {
  const progressRow = detailProgress || detailTask || {};
  const completedSource = detailTask || progressRow;
  const targetCount = progressRow.target_count ?? detailTask?.target_count;
  const display = (value) => hasValue(value) ? String(value) : '—';
  return `送样 ${display(fulfillmentCount(completedSource))}/${display(targetCount)} · 完成 ${display(completedFulfillmentCount(completedSource))}/${display(targetCount)}`;
}

export function requiresCancellationConfirmation(currentStatus, nextStatus) {
  return nextStatus === 'cancelled' && currentStatus !== 'cancelled';
}
