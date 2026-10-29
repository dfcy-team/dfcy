import { downloadApiFile, requestApi } from './request';
import { createIdempotencyKey } from './supplyChainV2';

const INTERNAL = '/api/internal/supply-chain/v2/';
const EXTERNAL = '/api/external/supplier/supply-chain/v2/';
const base = (supplier = false) => supplier ? EXTERNAL : INTERNAL;
const collectionName = (supplier = false) => supplier ? 'shipments' : 'supplier-shipments';
const enc = (id) => encodeURIComponent(id);

function write(method, url, data, key = createIdempotencyKey(), headers = {}) {
  return requestApi({ method, url, data, headers: { 'Idempotency-Key': key, ...headers } });
}
export { createIdempotencyKey };
export const fetchShipmentOrders = (supplier, params = {}) => requestApi({ method: 'get', url: `${base(supplier)}purchase-orders/`, params: { ...params, status: 'confirmed' } });
export const fetchShipmentOrder = (id, supplier = false) => requestApi({ method: 'get', url: `${base(supplier)}purchase-orders/${enc(id)}/` });
export const fetchShipmentOptions = (supplier = false, params = {}) => requestApi({ method: 'get', url: `${base(supplier)}shipment-options/`, params });
export const fetchShipments = (supplier = false, params = {}) => requestApi({ method: 'get', url: `${base(supplier)}${collectionName(supplier)}/`, params });
export const fetchShipment = (id, supplier = false) => requestApi({ method: 'get', url: `${base(supplier)}${collectionName(supplier)}/${enc(id)}/` });
export const createShipment = (data, supplier = false, key) => write('post', `${base(supplier)}${collectionName(supplier)}/`, data, key);
export const updateShipment = (id, data, supplier = false, key) => write('patch', `${base(supplier)}${collectionName(supplier)}/${enc(id)}/`, data, key);
export const submitShipment = (id, data, supplier = false, key) => write('post', `${base(supplier)}${collectionName(supplier)}/${enc(id)}/submit/`, data, key);
export const cancelShipment = (id, data, supplier = false, key) => write('post', `${base(supplier)}${collectionName(supplier)}/${enc(id)}/cancel/`, data, key);
export const markShipmentArrived = (id, data, key) => write('post', `${INTERNAL}${collectionName(false)}/${enc(id)}/arrival/`, data, key);
export const updateShipmentPrices = (id, data, key) => write('patch', `${INTERNAL}${collectionName(false)}/${enc(id)}/prices/`, data, key);
export function uploadShipmentAttachment(id, file, expected_version, supplier = false, key) {
  const form = new FormData(); form.append('file', file); form.append('expected_version', expected_version);
  return write('post', `${base(supplier)}${collectionName(supplier)}/${enc(id)}/attachments/`, form, key, { 'Content-Type': 'multipart/form-data' });
}
export const removeShipmentAttachment = (id, attachmentId, data, supplier = false, key) => write('post', `${base(supplier)}${collectionName(supplier)}/${enc(id)}/attachments/${enc(attachmentId)}/remove/`, data, key);
export const downloadShipmentAttachment = (id, attachmentId, filename, supplier = false) => downloadApiFile(`${base(supplier)}${collectionName(supplier)}/${enc(id)}/attachments/${enc(attachmentId)}/download/`, filename);

export const fetchDomesticCarriers=(id,supplier=false,params={})=>requestApi({method:'get',url:`${base(supplier)}${collectionName(supplier)}/${enc(id)}/domestic-carrier-options/`,params});
export const saveDomesticTransport=(id,data,supplier=false,key)=>write('put',`${base(supplier)}${collectionName(supplier)}/${enc(id)}/domestic-transport/`,data,key);
