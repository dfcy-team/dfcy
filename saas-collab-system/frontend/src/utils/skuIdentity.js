export function filterSpecValuesForDimensions(specValues, dimensions) {
  const next = { ...(specValues || {}) };
  const target = new Map((dimensions || []).map((dimension) => [dimension.code, dimension]));
  for (const [code, value] of Object.entries(next)) {
    const dimension = target.get(code);
    if (!dimension) {
      delete next[code];
      continue;
    }
    const choices = Array.isArray(dimension.values) ? dimension.values : [];
    if (choices.length && !choices.includes(value)) delete next[code];
  }
  return next;
}

export function specDimensionLabel(code, dimensions) {
  return (dimensions || []).find((dimension) => dimension.code === code)?.name || code;
}
