export function collectionRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  if (Array.isArray(data?.items)) return data.items;
  return [];
}

export function collectionTotal(data) {
  if (Number.isFinite(data?.count)) return data.count;
  return collectionRows(data).length;
}

export function detailData(data) {
  if (Array.isArray(data?.results)) return data.results[0] || {};
  if (Array.isArray(data?.items)) return data.items[0] || {};
  return data || {};
}

export function apiState(data, fallback = 'connected') {
  return data?.api_status || data?.status || fallback;
}

export function stateTagType(state) {
  if (state === 'connected') return 'success';
  if (state === 'error') return 'danger';
  if (state === 'fallback') return 'warning';
  return 'info';
}
