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

export const SKU_VARIANT_MODES = Object.freeze({
  COLOR_SPEC: 'color_spec',
  COLOR_ONLY: 'color_only',
  SPEC_ONLY: 'spec_only',
  SINGLE: 'single',
});

export function skuCombinationKey(colorCode = '', specValues = {}) {
  const specs = Object.keys(specValues || {})
    .sort()
    .map((code) => [code, String(specValues[code] ?? '').trim()]);
  return JSON.stringify([String(colorCode || '').trim(), specs]);
}

function cartesianSpecValues(dimensions, selectedValues, index = 0, current = {}) {
  if (index >= dimensions.length) return [{ ...current }];
  const dimension = dimensions[index];
  const values = normalizeBatchSelection(selectedValues?.[dimension.code]);
  if (!values.length) return [];
  return values.flatMap((value) => cartesianSpecValues(
    dimensions,
    selectedValues,
    index + 1,
    { ...current, [dimension.code]: value },
  ));
}

export function buildSkuCombinations(mode, colorCodes, dimensions = [], selectedValues = {}) {
  const usesColor = [SKU_VARIANT_MODES.COLOR_SPEC, SKU_VARIANT_MODES.COLOR_ONLY].includes(mode);
  const usesSpec = [SKU_VARIANT_MODES.COLOR_SPEC, SKU_VARIANT_MODES.SPEC_ONLY].includes(mode);
  const colorAxis = usesColor ? normalizeBatchSelection(colorCodes) : [''];
  const activeDimensions = usesSpec ? dimensions.filter((item) => item?.code) : [];
  const specAxis = usesSpec ? cartesianSpecValues(activeDimensions, selectedValues) : [{}];
  return colorAxis.flatMap((colorCode) => specAxis.map((specValues) => ({
    color_code: colorCode,
    spec_values: specValues,
    key: skuCombinationKey(colorCode, specValues),
  })));
}

export function calculatePackageVolume(length, width, height) {
  const values = [length, width, height].map((value) => Number(value));
  if (values.some((value) => !Number.isFinite(value) || value < 0)) return '';
  if (values.some((value) => value === 0)) return '0.000000';
  return ((values[0] * values[1] * values[2]) / 1000000).toFixed(6);
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
