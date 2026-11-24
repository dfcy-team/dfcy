const SCALE = 10000n;

export function fxPayload(amount, currency, rate) {
  if (currency === 'CNY') return {};
  if (rate === '' || rate == null) return {};
  const amountUnits = parseUnits(amount);
  const rateUnits = parseUnits(rate, 8);
  if (amountUnits <= 0n || rateUnits <= 0n) throw new Error('请输入有效的人民币汇率');
  const rateScale = 100000000n;
  const cnyUnits = (amountUnits * rateUnits + rateScale / 2n) / rateScale;
  return { exchange_rate: String(rate), cny_amount: `${cnyUnits / SCALE}.${String(cnyUnits % SCALE).padStart(4, '0')}` };
}

function parseUnits(value, precision = 4) {
  const match = String(value ?? '').trim().match(new RegExp(`^(\\d+)(?:\\.(\\d{1,${precision}}))?$`));
  if (!match) throw new Error(`金额最多四位小数，汇率最多${precision}位小数`);
  const scale = 10n ** BigInt(precision);
  return BigInt(match[1]) * scale + BigInt((match[2] || '').padEnd(precision, '0') || '0');
}

export function fxDisplay(row) {
  if (row?.cny_amount != null) return `人民币 ${row.cny_amount}（汇率 ${row.exchange_rate ?? '未登记'}）`;
  return row?.currency === 'CNY' ? `人民币 ${row.amount}` : '人民币金额未登记';
}
