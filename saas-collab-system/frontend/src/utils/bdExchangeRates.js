export const BD_EXCHANGE_RATE_CONFIG_KEY = 'influencers.bd.exchange_rates';
export const BD_EXCHANGE_RATE_CURRENCIES = Object.freeze(['PHP', 'MYR', 'THB', 'USD']);
export const MAX_BD_EXCHANGE_RATE_ROWS = 1000;

export function validateBdExchangeRates(rows, { allowEmpty = false } = {}) {
  if (!Array.isArray(rows) || (!allowEmpty && rows.length === 0) || rows.length > MAX_BD_EXCHANGE_RATE_ROWS) {
    throw new Error('请填写至少一条汇率，最多 1000 条。');
  }
  const seen = new Set();
  const rates = rows.map((row, index) => {
    const prefix = `第 ${index + 1} 行：`;
    if (!row || typeof row !== 'object' || Array.isArray(row) ||
        Object.keys(row).some((key) => !['currency', 'rate', 'effective_from', 'note'].includes(key))) {
      throw new Error(`${prefix}汇率记录格式不正确。`);
    }
    const currency = String(row.currency || '').trim().toUpperCase();
    if (typeof row.rate !== 'string') throw new Error(`${prefix}汇率必须为十进制文本，不能使用浮点数。`);
    const rate = row.rate.trim();
    const effectiveFrom = String(row.effective_from || '').trim();
    const note = row.note ?? '';
    if (!BD_EXCHANGE_RATE_CURRENCIES.includes(currency)) throw new Error(`${prefix}请选择支持的币种。`);
    if (!/^\d{1,10}(\.\d{1,10})?$/.test(rate) || !/[1-9]/.test(rate)) {
      throw new Error(`${prefix}汇率须大于 0，最多 10 位整数、10 位小数，不支持科学计数法。`);
    }
    const date = new Date(`${effectiveFrom}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(effectiveFrom) || Number.isNaN(date.getTime()) ||
        date.toISOString().slice(0, 10) !== effectiveFrom || effectiveFrom < '1900-01-01' || effectiveFrom > '2100-12-31') {
      throw new Error(`${prefix}适用日期须为 1900 至 2100 年内的有效日期。`);
    }
    if (typeof note !== 'string' || note.length > 240) throw new Error(`${prefix}备注最多 240 字。`);
    const key = `${currency}:${effectiveFrom}`;
    if (seen.has(key)) throw new Error(`${prefix}同一币种、同一适用日期不能重复。`);
    seen.add(key);
    return { currency, rate, effective_from: effectiveFrom, note: note.trim() };
  });
  return { rates: rates.sort((a, b) => a.currency.localeCompare(b.currency) || a.effective_from.localeCompare(b.effective_from)) };
}

export function readBdExchangeRateRows(value) {
  if (value == null) return [];
  if (typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some((key) => key !== 'rates')) {
    throw new Error('汇率配置格式异常，请联系管理员；未覆盖原版本。');
  }
  if (Array.isArray(value.rates) && value.rates.length === 0) return [];
  return validateBdExchangeRates(value.rates).rates;
}
