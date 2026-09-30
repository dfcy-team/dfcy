import { filterLabels } from './reportPresentation';

export const clone = (value) => JSON.parse(JSON.stringify(value));
export function datasetFilters(dataset) {
  if (!dataset) return [];
  return [...new Set([...(dataset.filters || []), ...(dataset.id.startsWith('inventory') ? ['include_virtual'] : ['platforms', 'store_ids'])])];
}
export function fieldLayout(config, dataset) {
  const columns = config.field_layout?.columns || (config.pivot ? [config.pivot] : []);
  const dimensions = config.dimensions || [];
  return {
    rows: dimensions.filter(key => !columns.includes(key)),
    columns: columns.filter(key => dimensions.includes(key)),
    filters: (config.field_layout?.filters || datasetFilters(dataset)).filter(key => datasetFilters(dataset).includes(key))
  };
}

// Used by drag/drop and the equivalent keyboard/touch controls.
export function moveField(config, dataset, field, zone, index) {
  const next = clone(config), layout = fieldLayout(next, dataset);
  const dimensions = dataset.dimensions.map(item => item.key), metrics = dataset.metrics.map(item => item.key);
  if (['rows', 'columns'].includes(zone)) {
    if (field.kind !== 'dimension' || !dimensions.includes(field.key)) return null;
    const total = new Set([...layout.rows, ...layout.columns, field.key]);
    if (total.size > 6) return null;
    layout.rows = layout.rows.filter(key => key !== field.key);
    layout.columns = layout.columns.filter(key => key !== field.key);
    if (zone === 'columns' && layout.columns.length >= 3) return null;
    layout[zone].splice(index ?? layout[zone].length, 0, field.key);
    next.dimensions = [...layout.rows, ...layout.columns];
    next.pivot = layout.columns[0] || '';
    if (layout.columns.length) next.chart = 'pivot';
  } else if (zone === 'metrics') {
    if (field.kind !== 'metric' || !metrics.includes(field.key)) return null;
    next.metrics = next.metrics.filter(key => key !== field.key);
    if (next.metrics.length >= 8) return null;
    next.metrics.splice(index ?? next.metrics.length, 0, field.key);
    if (!next.metrics.includes(next.chart_metric)) next.chart_metric = next.metrics[0];
  } else if (zone === 'filters') {
    if (field.kind !== 'filter' || !datasetFilters(dataset).includes(field.key)) return null;
    layout.filters = layout.filters.filter(key => key !== field.key);
    layout.filters.splice(index ?? layout.filters.length, 0, field.key);
  } else return null;
  next.field_layout = layout;
  return next;
}

export function removeField(config, dataset, key, zone) {
  const next = clone(config), layout = fieldLayout(next, dataset);
  if (zone === 'metrics') {
    if (next.metrics.length <= 1) return null;
    next.metrics = next.metrics.filter(item => item !== key);
    if (!next.metrics.includes(next.chart_metric)) next.chart_metric = next.metrics[0];
  } else if (zone === 'filters') {
    layout.filters = layout.filters.filter(item => item !== key);
    delete next.filters[key];
  } else {
    if (next.dimensions.length <= 1) return null;
    const needsCurrency = next.metrics.some(metric => dataset.metrics.find(item => item.key === metric)?.kind === 'money');
    if (key === 'currency' && needsCurrency) return null;
    layout[zone] = layout[zone].filter(item => item !== key);
    next.dimensions = [...layout.rows, ...layout.columns];
    next.pivot = layout.columns[0] || '';
  }
  if (next.ordering && ![...next.dimensions, ...next.metrics].includes(next.ordering.replace(/^-/, ''))) next.ordering = '';
  next.field_layout = layout;
  return next;
}

// Never combine row values: order counts across SKUs and currency totals are not additive.
export function matrixRows(rows, config, metric) {
  const columnKeys = config.field_layout?.columns?.length ? config.field_layout.columns : config.pivot ? [config.pivot] : [];
  const rowKeys = config.dimensions.filter(key => !columnKeys.includes(key));
  const columns = new Map(), groups = new Map();
  for (const source of rows) {
    const column = JSON.stringify(columnKeys.map(key => source[key] ?? null));
    const row = JSON.stringify(rowKeys.map(key => source[key] ?? null));
    if (!columns.has(column)) columns.set(column, columnKeys.map(key => source[key] ?? '未提供').join(' · '));
    if (!groups.has(row)) groups.set(row, { id: row, label: rowKeys.map(key => source[key] ?? '未提供').join(' · ') || '全部', cells: {} });
    groups.get(row).cells[column] = { value: source[metric], source };
  }
  return { columns: [...columns].map(([key, label]) => ({ key, label })), rows: [...groups.values()] };
}

export function chartData(rows, config, metric) {
  const selected = rows.slice(0, 40);
  const valid = row => row[metric] != null && row[metric] !== '' && Number.isFinite(Number(row[metric]));
  const max = Math.max(1, ...selected.filter(valid).map(row => Math.abs(Number(row[metric]))));
  const points = selected.flatMap((row, index) => valid(row) ? [{
    index, row, currency: row.currency, x: 60 + index * 810 / Math.max(1, selected.length - 1),
    y: 140 - Number(row[metric]) / max * 100, label: config.dimensions.map(key => row[key] ?? '未提供').join(' · '), value: row[metric]
  }] : []);
  const series = [];
  for (const point of points) {
    const previous = series.at(-1)?.at(-1);
    if (!previous || previous.currency !== point.currency || previous.index + 1 !== point.index) series.push([]);
    series.at(-1).push(point);
  }
  return { points, series };
}

export function filterLabel(key) { return filterLabels[key] || (key === 'include_virtual' ? '包含虚拟商品' : key); }
