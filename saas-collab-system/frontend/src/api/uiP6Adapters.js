function compact(params) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== '' && value !== null && value !== undefined)
  );
}

export function buildPeriodQuery(params = {}) {
  const { date_range: dateRange, ...query } = params;
  if (Array.isArray(dateRange) && dateRange.length === 2) {
    query.period_start = dateRange[0];
    query.period_end = dateRange[1];
  }
  return compact(query);
}

export function buildAnalyticsQuery(params = {}) {
  const query = buildPeriodQuery(params);
  if (query.store) {
    query.store_id = query.store;
    delete query.store;
  }
  if (query.warehouse) {
    query.warehouse_id = query.warehouse;
    delete query.warehouse;
  }
  delete query.risk_level;
  return compact(query);
}

export function buildFinanceAnalyticsQuery(params = {}) {
  return buildPeriodQuery(params);
}

export function normalizeAnalyticsResponse(response) {
  if (!response?.success || !response.data || typeof response.data !== 'object') return response;
  const quality = response.data.quality || {};
  const sourceResults = Array.isArray(response.data.results)
    ? response.data.results
    : (Array.isArray(response.data.metrics) ? response.data.metrics : []);
  const results = sourceResults.map((row) => ({
        ...row,
        metric_code: row.metric_code ?? row.code,
        metric_name: row.metric_name ?? row.label,
        metric_version: row.metric_version ?? quality.metric_version,
        quality_status: row.quality_status ?? row.quality ?? quality.status,
        updated_at: row.updated_at ?? quality.refreshed_at,
        is_missing: row.is_missing ?? row.value === null,
        platform: row.dimensions?.platform ?? row.platform,
        store_id: row.dimensions?.store_id ?? row.store_id ?? row.store,
        country: row.dimensions?.country ?? row.country,
        product_id: row.dimensions?.product_id ?? row.product_id,
        sku_id: row.dimensions?.sku_id ?? row.sku_id,
        warehouse_id: row.dimensions?.warehouse_id ?? row.warehouse_id ?? row.warehouse
      }));
  return { ...response, data: { ...response.data, results } };
}
