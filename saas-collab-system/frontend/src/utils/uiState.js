export function statusFromApiResponse(response, online = true) {
  if (!online || response?.code === 'HTTP_NETWORK_ERROR') return 'offline';
  if (response?.success && response?.data?.partial) return 'partial';
  if (response?.success) return 'ready';
  return {
    401: 'unauthenticated',
    403: 'forbidden',
    404: 'empty',
    409: 'conflict',
    422: 'invalid'
  }[response?.http_status] || 'error';
}
