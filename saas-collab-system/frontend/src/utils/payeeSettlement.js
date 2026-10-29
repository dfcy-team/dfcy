export const natureLabel = value => ({ corporate: '对公', personal: '对私', mixed: '混合结算', unclassified: '未标识' })[value] || '未标识';

export function amountUnits(value) {
  const text = String(value ?? '').trim();
  if (!/^\d{1,20}(?:\.\d{1,4})?$/.test(text)) throw new Error('金额须为非负数且最多4位小数');
  const [whole, fraction = ''] = text.split('.');
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'));
}

export function validateAllocations(rows, total) {
  const expected = amountUnits(total);
  if (!rows.length) {
    if (expected > 0n) throw new Error('请选择收款账户并填写对应累计金额');
    return [];
  }
  const seen = new Set();
  let sum = 0n;
  const output = rows.map((row, index) => {
    if (!row.account_id) throw new Error(`第${index + 1}行请选择收款账户`);
    if (seen.has(String(row.account_id))) throw new Error('收款账户重复，请合并同一账户的累计金额');
    seen.add(String(row.account_id));
    const units = amountUnits(row.amount);
    if (units <= 0n) throw new Error(`第${index + 1}行账户金额须大于0`);
    sum += units;
    return { account_id: row.account_id, amount: String(row.amount).trim() };
  });
  if (sum !== expected) throw new Error('各收款账户的累计金额合计须等于累计已结算金额');
  return output;
}
