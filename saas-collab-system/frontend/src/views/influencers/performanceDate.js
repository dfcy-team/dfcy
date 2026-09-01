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

export function calendarDayCount(startDay, endDay) {
  const start = Date.parse(`${startDay}T00:00:00Z`);
  const end = Date.parse(`${endDay}T00:00:00Z`);
  return Number.isFinite(start) && Number.isFinite(end) ? Math.floor((end - start) / 86400000) + 1 : null;
}

export function isDateRangeWithinLimit(startDay, endDay, maximumDays = 31) {
  const dayCount = calendarDayCount(startDay, endDay);
  return dayCount !== null && dayCount >= 1 && dayCount <= maximumDays;
}

export function bdPerformanceErrorMessage(response) {
  const message = response?.message || '';
  if (/date range must not exceed|日期范围.*超过/i.test(message)) return '统计范围最多支持 31 个自然日，请调整开始或结束日期';
  if (/end_date must not exceed|结束日期.*超过/i.test(message)) return '结束日期不能晚于昨日或当前已导入订单日期，请重新选择';
  return message || '绩效聚合数据加载失败';
}
