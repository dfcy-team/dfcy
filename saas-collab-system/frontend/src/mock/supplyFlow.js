import { successResponse } from './index';

const site = {
  id: 5101,
  site_code: 'SC-LOCAL-SOUTH',
  name: '华南本地集货站',
  region_code: 'CN-SOUTH',
  country_code: 'CN',
  province_state: '广东',
  city: '深圳',
  address_line: '本地开发地址（不发运）',
  contact_name: '本地操作员',
  contact_phone: '仅用于本地 Mock',
  is_active: true,
  version: 1
};

let sites = [structuredClone(site)];
let consolidations = [
  {
    id: 5201,
    consolidation_no: 'LC-LOCAL-001',
    region_code: 'CN-SOUTH',
    site: structuredClone(site),
    status: 'draft',
    version: 1,
    allocations: []
  }
];
let shipments = [];

const page = (items, params = {}) => {
  const pageNumber = Math.max(1, Number(params.page || 1));
  const pageSize = Math.min(100, Math.max(1, Number(params.page_size || 20)));
  const start = (pageNumber - 1) * pageSize;
  return { count: items.length, next: null, previous: null, results: items.slice(start, start + pageSize) };
};

const mock = (data) => successResponse({ ...data, api_status: 'mock' });

export const mockFetchSites = (params) => mock(page(sites, params));
export const mockCreateSite = (payload) => {
  const created = { ...structuredClone(site), ...payload, id: Math.max(...sites.map((item) => item.id), 5100) + 1, version: 1 };
  sites.push(created);
  return mock(created);
};
export const mockUpdateSite = (id, payload) => {
  const item = sites.find((row) => row.id === Number(id));
  if (!item) throw new Error('集货站点不存在');
  Object.assign(item, payload, { version: item.version + 1 });
  return mock(item);
};
export const mockDeactivateSite = (id) => mockUpdateSite(id, { is_active: false });

export const mockFetchConsolidations = (params) => mock(page(consolidations, params));
export const mockFetchConsolidation = (id) => {
  const item = consolidations.find((row) => row.id === Number(id));
  if (!item) throw new Error('集货单不存在');
  return mock(item);
};
export const mockCreateConsolidation = (payload) => {
  const created = {
    id: Math.max(...consolidations.map((item) => item.id), 5200) + 1,
    consolidation_no: payload.consolidation_no || `LC-LOCAL-${consolidations.length + 1}`,
    region_code: payload.region_code || site.region_code,
    site: structuredClone(sites.find((item) => item.id === Number(payload.site_id)) || site),
    status: 'draft', version: 1, allocations: []
  };
  consolidations.push(created);
  return mock(created);
};
export const mockConsolidationAction = (id, action, payload = {}) => {
  const item = consolidations.find((row) => row.id === Number(id));
  if (!item) throw new Error('集货单不存在');
  const transitions = { release: 'released', ready: 'ready_for_shipment', cancel: 'cancelled', receive: 'receiving' };
  item.status = transitions[action] || item.status;
  item.version += 1;
  return mock(item);
};

export const mockFetchShipments = (params) => mock(page(shipments, params));
export const mockFetchShipment = (id) => {
  const item = shipments.find((row) => row.id === Number(id));
  if (!item) throw new Error('发运单不存在');
  return mock(item);
};
export const mockCreateShipment = (payload) => {
  const created = { id: Math.max(...shipments.map((item) => item.id), 5300) + 1, ...payload, status: 'draft', version: 1, allocations: [] };
  shipments.push(created);
  return mock(created);
};
export const mockShipmentAction = (id, action) => {
  const item = shipments.find((row) => row.id === Number(id));
  if (!item) throw new Error('发运单不存在');
  const transitions = { allocate: 'loading', customs: 'customs_declared', dispatch: 'dispatched', 'port-arrival': 'port_arrived', 'warehouse-arrival': 'warehouse_arrived', clearance: 'warehouse_cleared', cancel: 'cancelled' };
  item.status = transitions[action] || item.status;
  item.version += 1;
  return mock(item);
};

export const resetMockSupplyFlow = () => {
  sites = [structuredClone(site)];
  consolidations = [
    { id: 5201, consolidation_no: 'LC-LOCAL-001', region_code: 'CN-SOUTH', site: structuredClone(site), status: 'draft', version: 1, allocations: [] }
  ];
  shipments = [];
};
