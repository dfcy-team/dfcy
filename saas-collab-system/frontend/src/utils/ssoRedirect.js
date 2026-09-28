export function safeLocalRedirect(value) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\') && !/[\r\n]/.test(value) ? value : '/';
}

export function safeSsoCallback(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.hash || url.search || url.pathname === '/') return null;
    return url;
  } catch {
    return null;
  }
}
