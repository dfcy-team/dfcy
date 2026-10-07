export function classifyBulkSyncJobs(jobs) {
  const first = jobs[0];
  const eligible = [];
  const skipped = [];
  for (const row of jobs) {
    let reason = '';
    if (row.platform !== first?.platform || row.resource_type !== first?.resource_type) reason = '平台或资源类型不同';
    else if (row.status === 'running' || row.schedule_state === 'running') reason = '任务正在运行';
    else if (row.status === 'queued' || row.schedule_state === 'queued') reason = '任务正在排队';
    (reason ? skipped : eligible).push(reason ? { id: row.id, reason } : row);
  }
  return { eligible, skipped };
}

function rangeValue(value) {
  // Legacy datetime inputs represent Beijing time; preserve explicit offsets and date-only ranges.
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(value) ? `${value}+08:00` : value;
}

export function buildBulkSyncJobPayload(fields, policy) {
  const payload = {};
  for (const key of ['max_retry_count', 'backoff_base_seconds', 'query_page_size', 'max_pages', 'max_records', 'overlap_minutes', 'collection_time_basis', 'execution_budget_seconds']) {
    if (fields.includes(key)) payload[key] = policy[key];
  }
  if (fields.includes('schedule')) {
    Object.assign(payload, { schedule_type: policy.schedule_type, timezone: policy.timezone,
      catch_up: policy.catch_up });
    if (policy.schedule_type === 'interval') payload.interval_minutes = policy.interval_minutes;
    if (['daily', 'weekly'].includes(policy.schedule_type)) payload.local_time = policy.local_time;
    if (policy.schedule_type === 'weekly') payload.weekdays = [...policy.weekdays];
  }
  if (fields.includes('query')) {
    payload.query_mode = policy.query_mode;
    if (policy.query_mode === 'incremental') payload.lookback_days = policy.lookback_days;
    else Object.assign(payload, { range_start_at: rangeValue(policy.range_start_at), range_end_at: rangeValue(policy.range_end_at) });
  }
  return payload;
}
