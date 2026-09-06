const hasValue = (value) => value !== undefined && value !== null && value !== '';

export function completedFulfillmentCount(row = {}) {
  return Number(row?.sample_fulfillment_completed_count ?? row?.completion_validation?.completed_count ?? 0);
}

export function fulfillmentCount(row = {}) {
  return Number(row?.sample_fulfillment_count ?? row?.sample_status_summary?.total ?? 0);
}

export function sampledInfluencerCount(row = {}) {
  return Number(
    row?.sample_fulfillment_influencer_count
    ?? row?.completion_validation?.sampled_influencer_count
    ?? fulfillmentCount(row)
  );
}

export function sampleProgressLabel(row = {}) {
  const targetCount = row?.target_count;
  const display = (value) => hasValue(value) ? String(value) : '—';
  return `${display(sampledInfluencerCount(row))}/${display(targetCount)}`;
}
export function outreachProgressLabel(detailProgress, detailTask) {
  const progressRow = detailProgress || detailTask || {};
  const countSource = detailTask || progressRow;
  const targetCount = progressRow.target_count ?? detailTask?.target_count;
  const display = (value) => hasValue(value) ? String(value) : '—';
  return `送样达人 ${display(sampledInfluencerCount(countSource))}/${display(targetCount)}`;
}

export function requiresCancellationConfirmation(currentStatus, nextStatus) {
  return nextStatus === 'cancelled' && currentStatus !== 'cancelled';
}
