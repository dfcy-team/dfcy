export function allocatedQty(row) {
  return (row.dispatch_allocations || []).reduce((sum, item) => sum + Number(item.quantity || 0), 0)
}

export function shippedQty(row) {
  const shippedStages = ['departed', 'arrived_port', 'arrived_warehouse']
  return (row.dispatch_allocations || []).reduce(
    (sum, item) => sum + (shippedStages.includes(item.stage) ? Number(item.quantity || 0) : 0), 0,
  )
}

function allocationBasis(item) {
  return item.billing_basis || item.freight_quote_snapshot?.billing_basis || ''
}

export function collectionStateText(row) {
  const allocations = row.dispatch_allocations || []
  const total = (row.lines || []).reduce((sum, line) => sum + Number(line.quantity || 0), 0)
  const allocated = allocatedQty(row)
  const shipped = shippedQty(row)
  const containerQty = allocations.reduce((sum, item) => sum + (allocationBasis(item) === 'container' ? Number(item.quantity || 0) : 0), 0)
  const looseQty = allocations.reduce((sum, item) => sum + (allocationBasis(item) === 'cbm' ? Number(item.quantity || 0) : 0), 0)
  const unknownQty = Math.max(0, allocated - containerQty - looseQty)
  const typeParts = [
    containerQty > 0 ? `整柜 ${containerQty} 件` : '',
    looseQty > 0 ? `散货 ${looseQty} 件` : '',
    unknownQty > 0 ? `类型待确认 ${unknownQty} 件` : '',
  ].filter(Boolean)
  const typeSummary = typeParts.join(' / ')
  const mixedType = typeParts.length > 1

  if (shipped > 0) {
    const progress = total > 0 && allocated >= total && shipped >= total ? `已全部发运 ${shipped} 件` : `部分发运 ${shipped} 件`
    return `${mixedType ? '混合运输' : unknownQty > 0 ? '运输类型待确认' : containerQty > 0 ? '整柜发运' : '散货'} · ${progress}${mixedType ? ` · ${typeSummary}` : ''}`
  }
  if (mixedType) return `混合运输 · ${typeSummary}`
  if (containerQty > 0) return total > 0 && allocated >= total ? '整柜发运 · 已全部分配' : `整柜发运 · 已分配 ${containerQty} 件`
  if (looseQty > 0) return `${row.collection_arrived ? '散货 · 已到集货中心' : '散货 · 未到集货中心'} · 已分配 ${looseQty} 件`
  if (unknownQty > 0) {
    const original = row.delivery_mode === 'factory_loading' ? '上门装柜' : row.collection_arrived ? '已到集货中心' : '未到集货中心'
    return `${original} · 类型待确认 ${unknownQty} 件`
  }
  return row.delivery_mode === 'factory_loading' ? '上门装柜' : row.collection_arrived ? '散货 · 已到集货中心' : '散货 · 未到集货中心'
}
