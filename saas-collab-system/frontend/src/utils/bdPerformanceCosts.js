export const BD_COST_BASIS = 'sample_plus_actual_commissions';

export const BD_COST_COLUMNS = [
  { key: 'sample_cost', label: '送样成本', complete: 'sample_cost_complete' },
  { key: 'actual_standard_commission', label: '实际标准佣金', complete: 'actual_standard_commission_complete' },
  { key: 'actual_ads_commission', label: '实际广告佣金', complete: 'actual_ads_commission_complete' },
  { key: 'total_cost', label: '总成本', complete: 'cost_complete' }
];

export function costDisplay(row, column, formatMoney) {
  if (row?.[column.complete] === true && row[column.key] != null) return formatMoney(row[column.key]);
  const known = row?.[`known_${column.key}`];
  return known == null ? '待补齐' : `已知 ${formatMoney(known)}（未完整）`;
}

export function costCsvColumns() {
  return BD_COST_COLUMNS.flatMap(({ key, label, complete }) => {
    const columns = [[label, key], [`${label}已知小计`, `known_${key}`], [`${label}完整`, complete]];
    if (key !== 'total_cost') columns.push(
      [`缺少${label}金额记录`, `missing_${key}_count`],
      [`缺少${label}汇率记录`, `missing_${key}_exchange_rate_count`]
    );
    return columns;
  });
}
