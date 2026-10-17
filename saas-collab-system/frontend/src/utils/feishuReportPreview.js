const validDate = value => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
};

export function safeFeishuExternalUrl(value) {
  if (typeof value !== 'string') return '';
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
  } catch (_error) {
    return '';
  }
}

export function projectFeishuCard(card) {
  if (!card || typeof card !== 'object' || card.schema !== '2.0') return null;
  const elements = Array.isArray(card.body?.elements) ? card.body.elements : [];
  return {
    schema: '2.0',
    elements: elements.flatMap(element => {
      if (element?.tag === 'markdown' && typeof element.content === 'string') {
        return [{ tag: 'markdown', content: element.content }];
      }
      if (element?.tag === 'hr') return [{ tag: 'hr' }];
      if (element?.tag === 'chart') {
        const spec = element.chart_spec;
        if (spec?.type !== 'bar' || !Array.isArray(spec.data?.values)) return [];
        const values = spec.data.values.flatMap(row => typeof row?.country === 'string' && Number.isFinite(row?.value)
          ? [{ country: row.country, value: row.value }]
          : []);
        return [{
          tag: 'chart',
          chart_spec: {
            type: 'bar',
            data: { values },
            xField: 'country',
            yField: 'value',
            title: { text: typeof spec.title?.text === 'string' ? spec.title.text : '' }
          }
        }];
      }
      if (element?.tag === 'button' && element.text?.tag === 'plain_text' && typeof element.text.content === 'string') {
        const behavior = Array.isArray(element.behaviors)
          ? element.behaviors.find(item => item?.type === 'open_url' && typeof item.default_url === 'string')
          : null;
        const url = safeFeishuExternalUrl(behavior?.default_url);
        return [{ tag: 'button', text: element.text.content, url }];
      }
      return [];
    })
  };
}

export function feishuReportLocation(datasets, query = {}) {
  const datasetId = typeof query.feishu_dataset === 'string' ? query.feishu_dataset : '';
  const dataset = datasets.find(item => item.id === datasetId);
  if (!dataset) return null;
  const allowedFilters = new Set(dataset.filters || []);
  const routeQuery = { tab: 'analysis', feishu_dataset: datasetId };
  for (const key of ['date_from', 'date_to']) {
    const value = query[key];
    if (allowedFilters.has(key) && validDate(value)) routeQuery[key] = value;
  }
  const scalarString = value => typeof value === 'string';
  const validStoreId = value => scalarString(value) && value.length <= 19 && /^[0-9]+$/.test(value) && /[1-9]/.test(value);
  const validRegion = value => scalarString(value) && /^[A-Z]{2,3}$/.test(value);
  const validCurrency = value => scalarString(value) && /^[A-Z]{3}$/.test(value);
  for (const [key, validate] of [['store_id', validStoreId], ['region', validRegion], ['currency', validCurrency]]) {
    const value = query[key];
    if (allowedFilters.has(key) && validate(value)) routeQuery[key] = value;
  }
  return { dataset, query: routeQuery };
}

export function initializeFeishuReportConfig(datasets, query, defaultsForDataset) {
  const location = feishuReportLocation(datasets, query);
  if (!location) return null;
  const filters = defaultsForDataset(location.dataset);
  for (const key of ['date_from', 'date_to', 'store_id', 'region', 'currency']) {
    if (location.query[key]) filters[key] = location.query[key];
  }
  return { dataset: location.dataset.id, ...location.dataset.defaults, filters, chart: 'table', pivot: '', ordering: '' };
}
