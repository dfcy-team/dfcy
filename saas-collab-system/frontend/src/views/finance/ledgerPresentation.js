export function ledgerMoney(value) {
  if (value == null) return '—';
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return '—';
  const [integer, fraction = ''] = text.split('.');
  return `${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.padEnd(2, '0').replace(/0+$/, '').padEnd(2, '0')}`;
}

export function ledgerCsv(items, view, kinds) {
  const columns = ['国家','店铺','订单号','币种'];
  if (view === 'detail') columns.push('财务日期','类型','金额','状态','来源','说明');
  else columns.push(...Object.values(kinds), '收支差额','待核对');
  const escape = value => {
    let text = String(value ?? '');
    if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"','""')}"`;
  };
  const rows = items.map(row => [row.country, row.store_code, row.external_order_id, row.currency,
    ...(view === 'detail' ? [row.date,kinds[row.kind],row.amount,row.status,row.source,row.description]
      : [...Object.keys(kinds).map(kind => row.cells[kind]?.amount ?? (row.cells[kind]?.reference_amount != null ? `${row.cells[kind].reference_amount}（参考，不计入差额）` : '')),row.balance,row.pending_count])]);
  return [columns,...rows].map(row => row.map(escape).join(',')).join('\r\n');
}
