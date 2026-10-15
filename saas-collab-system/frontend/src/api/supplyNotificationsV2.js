import { downloadApiFile, requestApi } from './request';
import { createIdempotencyKey } from './supplyChainV2';

const BASE = '/api/internal/supply-chain/v2/';
const keys = new Map();
const enc = (value) => encodeURIComponent(value);
const read = (url, params) => requestApi({ method: 'get', url: `${BASE}${url}`, ...(params ? { params } : {}) });
const write = (key, url, data, method = 'post') => {
  const idempotencyKey = keys.get(key) || createIdempotencyKey();
  keys.set(key, idempotencyKey);
  return requestApi({ method, url: `${BASE}${url}`, data, headers: { 'Idempotency-Key': idempotencyKey } })
    .then((result) => {
      // requestApi returns a normalized envelope even for network failures.
      // Preserve the key until the server result is known.
      if (result?.success || (result?.http_status >= 400 && result.http_status < 500 && result.http_status !== 408)) keys.delete(key);
      return result;
    });
};

export const fetchNotificationChannels = () => read('notification-channels/');
export const createNotificationChannel = (data) => write('channel:create', 'notification-channels/', data);
export const updateNotificationChannel = (id, data) => write(`channel:${id}`, `notification-channels/${enc(id)}/`, data, 'put');
export const setNotificationChannelCredentials = (id, data) => write(`credentials:${id}`, `notification-channels/${enc(id)}/credentials/`, data);
export const checkNotificationChannel = (id, data) => write(`check:${id}`, `notification-channels/${enc(id)}/check/`, data);
export const qualifyNotificationChannel = (id, data) => write(`qualify:${id}`, `notification-channels/${enc(id)}/qualify/`, data);
export const fetchNotificationCallbackLink = (id) => read(`notification-channels/${enc(id)}/callback-link/`);

export const fetchSupplierNotificationBinding = (supplierId) => read(`suppliers/${enc(supplierId)}/notification-binding/`);
export const saveSupplierNotificationBinding = (supplierId, data) => write(`binding:${supplierId}`, `suppliers/${enc(supplierId)}/notification-binding/`, data, 'put');
export const fetchPurchaseOrderNotification = (orderId) => read(`purchase-orders/${enc(orderId)}/notification/`);
export const fetchSupplyNotifications = (params = {}) => read('notifications/', params);
export const fetchSupplyNotification = (id) => read(`notifications/${enc(id)}/`);
export const prepareSupplyNotification = (id, data) => write(`prepare:${id}`, `notifications/${enc(id)}/prepare/`, data);
export const retargetSupplyNotification = (id, data) => write(`retarget:${id}`, `notifications/${enc(id)}/retarget/`, data);
export const reconcileSupplyNotification = (id, data) => write(`reconcile:${id}`, `notifications/${enc(id)}/reconcile/`, data);
export const retrySupplyNotificationPart = (id, partId, data) => write(`retry:${id}:${partId}`, `notifications/${enc(id)}/parts/${enc(partId)}/retry/`, data);
export const verifySupplyNotificationPart = (id, partId, data) => write(`verify:${id}:${partId}`, `notifications/${enc(id)}/parts/${enc(partId)}/verify/`, data);
export const downloadSupplyNotificationPart = (id, partId, filename) => downloadApiFile(
  `${BASE}notifications/${enc(id)}/parts/${enc(partId)}/download/`, filename
);
