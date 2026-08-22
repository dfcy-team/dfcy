export function normalizeSkuPrefixes(prefixes = []) {
  return [...new Set(prefixes.map((value) => String(value || '').trim()).filter(Boolean))].sort();
}

export function applyProductCandidate(form, candidate) {
  const prefixes = normalizeSkuPrefixes(candidate?.sku_prefixes);
  form.store = candidate?.store_id ?? null;
  form.sku_prefix = prefixes.join(',');
  return prefixes;
}
