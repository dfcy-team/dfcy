function platformKey(job) {
  return String(job.platform || '').trim().toLowerCase();
}

function subjectKey(job) {
  if (job.subject_key) return String(job.subject_key);
  const type = job.subject_type || (job.warehouse_id ? 'warehouse' : 'store');
  const identity = job.store_id || job.warehouse_id || job.subject_code || job.subject_name || 'unbound';
  return `${type}:${identity}`;
}

export function groupSyncJobsForDisplay(jobs) {
  return [...jobs].sort((a, b) =>
    platformKey(a).localeCompare(platformKey(b))
    || String(a.subject_name || '').localeCompare(String(b.subject_name || ''), 'zh-CN')
    || subjectKey(a).localeCompare(subjectKey(b))
    || String(a.resource_type || '').localeCompare(String(b.resource_type || ''))
    || Number(a.id) - Number(b.id)
  );
}

export function syncJobGroupSpan(rows, rowIndex, property) {
  if (property !== 'platform' && property !== 'subject_name') return [1, 1];
  const key = (job) => property === 'platform'
    ? platformKey(job)
    : `${platformKey(job)}:${subjectKey(job)}`;
  if (rowIndex > 0 && key(rows[rowIndex]) === key(rows[rowIndex - 1])) return [0, 0];
  let count = 1;
  while (rowIndex + count < rows.length && key(rows[rowIndex]) === key(rows[rowIndex + count])) count += 1;
  return [count, 1];
}
