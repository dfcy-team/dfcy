import { successResponse } from './index';

const mockOrder = {
  id: 9001,
  tenant_id: 1,
  order_no: 'SC-LOCAL-20260725-001',
  supplier_id: 1001,
  supplier_code: 'demo-supplier',
  supplier_name: '本地演示供应商',
  order_date: '2026-07-25',
  expected_delivery_date: '2026-08-25',
  currency: 'CNY',
  notes: '仅用于架构员主机 SC-F1 本地开发',
  status: 'pending',
  total_quantity: 100,
  completed_quantity: 0,
  line_count: 1,
  version: 1,
  source_system: null,
  source_table: null,
  source_record_id: null,
  accepted_at: null,
  production_started_at: null,
  production_completed_at: null,
  created_at: '2026-07-25T08:00:00Z',
  updated_at: '2026-07-25T08:00:00Z',
  lines: [
    {
      id: 1,
      line_no: 1,
      sku_id: 2001,
      sku_code_snapshot: 'SC-DEMO-SKU',
      product_name_snapshot: '本地演示商品',
      quantity: 100,
      unit_price: '12.5000',
      expected_delivery_date: '2026-08-25'
    }
  ],
  progress_entries: [],
  events: []
};

let orders = [structuredClone(mockOrder)];

const summary = (order) => ({
  ...order,
  line_count: order.lines.length,
  total_quantity: order.lines.reduce((total, line) => total + Number(line.quantity || 0), 0)
});

export const mockFetchSupplyOrders = (params = {}) => {
  const search = String(params.search || '').toLowerCase();
  const status = String(params.status || '');
  const page = Math.max(1, Number(params.page || 1));
  const pageSize = Math.min(100, Math.max(1, Number(params.page_size || 20)));
  const filtered = orders
    .filter((order) => !search || `${order.order_no} ${order.supplier_name}`.toLowerCase().includes(search))
    .filter((order) => !status || order.status === status);
  const start = (page - 1) * pageSize;
  const results = filtered.slice(start, start + pageSize).map(summary);
  return successResponse({ count: filtered.length, results, api_status: 'mock' });
};

export const mockFetchSupplyOrder = (id) => {
  const order = orders.find((item) => item.id === Number(id));
  if (!order) throw new Error('供应链采购单不存在');
  return successResponse({ ...summary(order), api_status: 'mock' });
};

export const mockCreateSupplyOrder = (payload) => {
  const total = payload.lines.reduce((value, line) => value + Number(line.quantity || 0), 0);
  const order = {
    ...structuredClone(mockOrder),
    ...payload,
    id: Math.max(...orders.map((item) => item.id), 9000) + 1,
    supplier_code: `supplier-${payload.supplier_id}`,
    supplier_name: `本地供应商 ${payload.supplier_id}`,
    currency: String(payload.currency || 'CNY').toUpperCase(),
    status: 'pending',
    total_quantity: total,
    completed_quantity: 0,
    line_count: payload.lines.length,
    version: 1,
    lines: payload.lines.map((line, index) => ({
      ...line,
      id: index + 1,
      sku_code_snapshot: `SKU-${line.sku_id}`,
      product_name_snapshot: `本地商品 ${line.sku_id}`
    })),
    progress_entries: [],
    events: []
  };
  orders = [order, ...orders];
  return successResponse({ ...summary(order), api_status: 'mock' });
};

export const mockRunSupplyOrderAction = (id, action, payload = {}) => {
  const order = orders.find((item) => item.id === Number(id));
  if (!order) throw new Error('供应链采购单不存在');
  const now = new Date().toISOString();
  const before = order.status;
  const transitions = {
    accept: ['pending', 'accepted'],
    'start-production': ['accepted', 'in_production'],
    'update-progress': ['in_production', 'in_production'],
    'complete-production': ['in_production', 'production_completed']
  };
  const transition = transitions[action];
  if (!transition) throw new Error('不支持的采购单动作');
  if (order.status !== transition[0]) throw new Error('当前采购单状态不允许执行该动作');
  if (action === 'update-progress') {
    const quantity = Number(payload.completed_quantity);
    if (
      !Number.isInteger(quantity)
      || quantity < order.completed_quantity
      || quantity > order.total_quantity
    ) {
      throw new Error('生产进度必须为整数、单调递增且不能超过采购数量');
    }
  }
  if (
    action === 'complete-production'
    && order.completed_quantity !== order.total_quantity
  ) {
    throw new Error('完成数量达到采购数量后才能标记生产完成');
  }

  order.status = transition[1];
  if (action === 'accept') order.accepted_at = now;
  if (action === 'start-production') order.production_started_at = now;
  if (action === 'update-progress') {
    order.completed_quantity = Number(payload.completed_quantity);
    order.progress_entries.unshift({
      id: order.progress_entries.length + 1,
      completed_quantity: order.completed_quantity,
      progress_percent: ((order.completed_quantity / order.total_quantity) * 100).toFixed(2),
      note: payload.note || '',
      created_at: now
    });
  }
  if (action === 'complete-production') order.production_completed_at = now;
  order.version += 1;
  order.updated_at = now;
  order.events.unshift({
    id: order.events.length + 1,
    action: action.replaceAll('-', '_'),
    before_status: before,
    after_status: order.status,
    created_at: now
  });
  return successResponse({
    replayed: false,
    order: { ...summary(order), api_status: 'mock' },
    api_status: 'mock'
  });
};

export function resetMockSupplyOrders() {
  orders = [structuredClone(mockOrder)];
}
