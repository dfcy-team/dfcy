import { downloadApiFile, requestApi } from './request';

const BASE = '/api/internal/supply-chain/v2/';

export function createIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16);
    return (character === 'x' ? random : (random & 0x3) | 0x8).toString(16);
  });
}

function write(method, url, data, key) {
  return requestApi({
    method,
    url,
    data,
    headers: { 'Idempotency-Key': key }
  });
}

function collection(name, params) {
  return requestApi({ method: 'get', url: `${BASE}${name}/`, params });
}

function detail(name, id) {
  return requestApi({ method: 'get', url: `${BASE}${name}/${encodeURIComponent(id)}/` });
}

export const fetchPurchaseOrders = (params) => collection('purchase-orders', params);
export const fetchPurchaseOrder = (id) => detail('purchase-orders', id);
export const createPurchaseOrder = (data, key) => write('post', `${BASE}purchase-orders/`, data, key);
export const updatePurchaseOrder = (id, data, key) => write('patch', `${BASE}purchase-orders/${encodeURIComponent(id)}/`, data, key);
export const confirmPurchaseOrder = (id, data, key) => write('post', `${BASE}purchase-orders/${encodeURIComponent(id)}/confirm/`, data, key);
export const cancelPurchaseOrder = (id, data, key) => write('post', `${BASE}purchase-orders/${encodeURIComponent(id)}/cancel/`, data, key);
export const updatePurchaseOrderMetadata = (id, data, key) => write('patch', `${BASE}purchase-orders/${encodeURIComponent(id)}/metadata/`, data, key);
export const fetchSupplyOptions = (params) => collection('options', params);

export const fetchSuppliers = (params) => collection('suppliers', params);
export const createSupplier = (data, key) => write('post', `${BASE}suppliers/`, data, key);
export const updateSupplier = (id, data, key) => write('patch', `${BASE}suppliers/${encodeURIComponent(id)}/`, data, key);

export const fetchFreightCompanies = (params) => collection('freight-companies', params);
export const createFreightCompany = (data, key) => write('post', `${BASE}freight-companies/`, data, key);
export const updateFreightCompany = (id, data, key) => write('patch', `${BASE}freight-companies/${encodeURIComponent(id)}/`, data, key);

export const fetchSupplierPrices = (params) => collection('supplier-prices', params);
export const saveSupplierPrice = (data, key) => write('post', `${BASE}supplier-prices/`, data, key);
export const fetchSupplierPriceHistory = (id, params = {}) => requestApi({
  method: 'get',
  url: `${BASE}supplier-prices/${encodeURIComponent(id)}/history/`,
  params
});

export function previewImport(file, key) {
  const data = new FormData();
  data.append('file', file);
  return requestApi({
    method: 'post',
    url: `${BASE}imports/`,
    data,
    timeout: 60000,
    headers: { 'Idempotency-Key': key }
  });
}

export const commitImport = (id, data, key) => write('post', `${BASE}imports/${encodeURIComponent(id)}/commit/`, data, key);

export const downloadImportTemplate = () => downloadApiFile(`${BASE}imports/template/`, 'supply-chain-import-template.xlsx');
export const downloadPurchaseExcel = (id, number) => downloadApiFile(
  `${BASE}purchase-orders/${encodeURIComponent(id)}/excel/`,
  `${number || id}.xlsx`
);
export const downloadPurchaseLabels = (id, number) => downloadApiFile(
  `${BASE}purchase-orders/${encodeURIComponent(id)}/labels/`,
  `${number || id}-labels.pdf`
);
