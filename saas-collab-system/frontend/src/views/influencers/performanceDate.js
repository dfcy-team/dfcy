const pad = (value) => String(value).padStart(2, '0');

export function localDateLabel(offset = 0, now = new Date()) {
  const value = new Date(now);
  value.setHours(0, 0, 0, 0);
  value.setDate(value.getDate() + offset);
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

export function defaultCompletedDateRange(now = new Date()) {
  return {
    startDay: localDateLabel(-7, now),
    endDay: localDateLabel(-1, now)
  };
}
