// The API already expresses timestamps in the supply-chain business timezone.
// Keep that wall-clock time instead of reinterpreting it in the browser timezone.
export function formatDocumentTime(value) {
  if (!value) return '—';
  return String(value).replace('T', ' ').replace(/(?:Z|[+-]\d{2}:\d{2})$/, '');
}
