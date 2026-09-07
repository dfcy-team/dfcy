/**
 * Normalize values entered in the batch SKU form before sending them to the
 * API. Element Plus returns arrays for multiple selects, but accepting a
 * scalar keeps restored/programmatic forms safe too.
 */
export function normalizeBatchSelection(values) {
  const source = Array.isArray(values) ? values : values == null ? [] : [values];
  const seen = new Set();
  return source
    .map((value) => String(value ?? '').trim())
    .filter((value) => {
      if (!value || seen.has(value)) return false;
      seen.add(value);
      return true;
    });
}

/**
 * Count the Cartesian product represented by the form. An omitted dimension
 * contributes one option, allowing the backend to apply its default value.
 */
export function skuBatchCombinationCount(colorCodes, specValues = {}) {
  const colors = normalizeBatchSelection(colorCodes);
  if (!colors.length) return 0;

  return Object.values(specValues || {}).reduce(
    (count, values) => count * Math.max(1, normalizeBatchSelection(values).length),
    colors.length,
  );
}

/** Build the stable request shape consumed by the batch SKU endpoint. */
export function buildSkuBatchPayload(spu, colorCodes, specValues = {}) {
  const payload = {
    spu,
    color_codes: normalizeBatchSelection(colorCodes),
    spec_values: {},
  };

  Object.entries(specValues || {}).forEach(([code, values]) => {
    const normalized = normalizeBatchSelection(values);
    if (normalized.length) payload.spec_values[code] = normalized;
  });

  return payload;
}
