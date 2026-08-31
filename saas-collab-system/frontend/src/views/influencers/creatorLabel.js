function hasValue(value) {
  return value !== undefined && value !== null && value !== '';
}

export function normalizedCreatorHandle(value) {
  return String(value ?? '').trim().replace(/^@+/, '').trim();
}

export function creatorDisplayName(value = {}) {
  const name = value.display_name
    || value.influencer_display_name
    || value.name
    || value.influencer_name
    || value.code
    || value.influencer_code;
  if (hasValue(name)) return String(name);
  const fallbackId = value.influencer ?? value.id;
  return hasValue(fallbackId) ? `达人 ${fallbackId}` : '—';
}

export function creatorHandleFirst(value = {}) {
  const handle = normalizedCreatorHandle(value.handle ?? value.influencer_handle);
  return handle || creatorDisplayName(value);
}

export function creatorOptionLabel(value = {}) {
  const handle = normalizedCreatorHandle(value.handle ?? value.influencer_handle);
  const displayName = creatorDisplayName(value);
  const primary = handle || displayName;
  const details = [];
  if (handle && displayName && normalizedCreatorHandle(displayName).toLowerCase() !== handle.toLowerCase()) {
    details.push(displayName);
  }
  const platform = value.platform || value.influencer_platform;
  if (hasValue(platform)) details.push(String(platform));
  return details.length ? `${primary}（${details.join(' · ')}）` : primary;
}
