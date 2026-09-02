const hasValue = (value) => value !== undefined && value !== null && value !== '';

export function completedFulfillmentCount(row = {}) {
  return Number(row?.sample_fulfillment_completed_count ?? row?.completion_validation?.completed_count ?? 0);
}

export function outreachProgressLabel(detailProgress, detailTask) {
  const progressRow = detailProgress || detailTask || {};
  const completedSource = detailTask || progressRow;
  const targetCount = progressRow.target_count ?? detailTask?.target_count;
  const display = (value) => hasValue(value) ? String(value) : '—';
  return `${display(completedFulfillmentCount(completedSource))}/${display(targetCount)}`;
}

export function requiresCancellationConfirmation(currentStatus, nextStatus) {
  return nextStatus === 'cancelled' && currentStatus !== 'cancelled';
}
