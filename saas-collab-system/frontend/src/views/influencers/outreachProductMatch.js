export function normalizeSkuPrefixes(prefixes = []) {
  return [...new Set(prefixes.map((value) => String(value || '').trim()).filter(Boolean))].sort();
}

export function applyProductCandidate(form, candidate) {
  const prefixes = normalizeSkuPrefixes(candidate?.sku_prefixes);
  form.store = candidate?.store_id ?? null;
  form.sku_prefix = prefixes.join(',');
  return prefixes;
}

export function applyStoreSelection(form, storeId, candidates = []) {
  const candidate = candidates.find((item) => String(item.store_id) === String(storeId));
  if (!candidate) {
    form.store = storeId;
    return [];
  }
  return applyProductCandidate(form, candidate);
}
