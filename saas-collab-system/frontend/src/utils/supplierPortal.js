export function supplierRedirect(value) {
  if (typeof value !== 'string' || !/^\/supplier\/(orders|shipments)(\/|\?|$)/.test(value) || value.includes('\\')) return '/supplier/orders';
  try {
    const url = new URL(value, 'https://supplier.invalid');
    return url.origin === 'https://supplier.invalid' && /^\/supplier\/(orders|shipments)(\/|$)/.test(url.pathname)
      ? `${url.pathname}${url.search}` : '/supplier/orders';
  } catch { return '/supplier/orders'; }
}
