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

export function normalizeInventoryAnalysisResponse(response) {
  if (!response?.success || !response.data) return response;
  const data = response.data;
  if (data.quality?.metric_version !== 'inventory_snapshot.v1') {
    return { ...response, data: { ...data, count: 0, results: [], metrics: [], trend: [],
      quality: { score: null, status_label: '暂无库存快照', note: '尚无真实库存快照，不能计算 SKU 映射率。' },
      trend_message: '暂无库存快照，无法展示历史变化。' } };
  }
  const quality = data.quality;
  const points = (data.trend || []).map(point => ({ label: point.date, value: point.total }));
  return { ...response, data: { ...data,
    quality: { ...quality,
      score: quality.total_count ? quality.score : null,
      status_label: !quality.total_count ? '暂无样本' : quality.mapped_count === quality.total_count ? '已全部关联' : '待关联',
      note: `当前范围 ${quality.total_count || 0} 条仓库 SKU，已关联内部 SKU ${quality.mapped_count || 0} 条。未关联不代表库存数量错误；关联后才能进行内部商品分析。`,
    },
    results: (data.results || []).map(row => ({ ...row,
      internal_sku: row.internal_sku || '未关联',
      mapping_status: row.internal_sku ? '已关联' : '未关联',
      snapshot_time: row.snapshot_at_utc ? new Date(row.snapshot_at_utc).toISOString().replace('T', ' ').slice(0, 19) : '--',
    })),
    trend: points.length >= 2 ? points : [],
    trend_message: points.length === 1 ? '当前范围仅有 1 天快照，尚不足以展示历史趋势。' : '当前范围暂无库存快照。',
  } };
}
