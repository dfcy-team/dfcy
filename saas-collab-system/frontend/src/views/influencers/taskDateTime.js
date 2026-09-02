const SHANGHAI_TIME_ZONE = 'Asia/Shanghai';

const formatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: SHANGHAI_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false
});

export function formatTaskDateTime(value) {
  if (value === null || value === undefined || String(value).trim() === '') return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const parts = Object.fromEntries(
    formatter.formatToParts(date).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value])
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}
