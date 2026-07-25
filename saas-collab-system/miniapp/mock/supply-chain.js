"use strict";

const orders = [
  {
    id: 9001,
    order_no: "SC-LOCAL-20260725-001",
    supplier_id: 1001,
    supplier_code: "demo-supplier",
    supplier_name: "本地演示供应商",
    order_date: "2026-07-25",
    expected_delivery_date: "2026-08-25",
    status: "pending",
    total_quantity: 100,
    completed_quantity: 0,
    version: 1,
    accepted_at: null,
    production_started_at: null,
    production_completed_at: null,
    lines: [
      {
        id: 1,
        line_no: 1,
        sku_id: 2001,
        sku_code_snapshot: "SC-DEMO-SKU",
        product_name_snapshot: "本地演示商品",
        quantity: 100,
        expected_delivery_date: "2026-08-25"
      }
    ],
    progress_entries: []
  }
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function getMockSupplyOrders(params = {}) {
  const page = Math.max(1, Number(params.page || 1));
  const pageSize = Math.min(100, Math.max(1, Number(params.page_size || 20)));
  const start = (page - 1) * pageSize;
  return {
    count: orders.length,
    next: null,
    previous: null,
    results: clone(orders.slice(start, start + pageSize))
  };
}

function getMockSupplyOrder(id) {
  const order = orders.find((item) => String(item.id) === String(id));
  if (!order) {
    const error = new Error("供应链采购单不存在");
    error.code = "NOT_FOUND";
    throw error;
  }
  return clone(order);
}

function runMockSupplyOrderAction(id, action, payload = {}) {
  const order = orders.find((item) => String(item.id) === String(id));
  if (!order) {
    const error = new Error("供应链采购单不存在");
    error.code = "NOT_FOUND";
    throw error;
  }
  const now = new Date().toISOString();
  if (action === "accept" && order.status === "pending") {
    order.status = "accepted";
    order.accepted_at = now;
  } else if (action === "start-production" && order.status === "accepted") {
    order.status = "in_production";
    order.production_started_at = now;
  } else if (action === "update-progress" && order.status === "in_production") {
    const quantity = Number(payload.completed_quantity);
    if (quantity < order.completed_quantity || quantity > order.total_quantity) {
      throw new Error("生产进度必须单调递增且不能超过采购数量");
    }
    order.completed_quantity = quantity;
    order.progress_entries.unshift({
      id: order.progress_entries.length + 1,
      completed_quantity: quantity,
      progress_percent: ((quantity / order.total_quantity) * 100).toFixed(2),
      note: payload.note || "",
      created_at: now
    });
  } else if (
    action === "complete-production"
    && order.status === "in_production"
    && order.completed_quantity === order.total_quantity
  ) {
    order.status = "production_completed";
    order.production_completed_at = now;
  } else {
    throw new Error("当前采购单状态不允许执行该动作");
  }
  order.version += 1;
  return {
    replayed: false,
    order: clone(order)
  };
}

function resetMockSupplyOrders() {
  orders[0].status = "pending";
  orders[0].completed_quantity = 0;
  orders[0].version = 1;
  orders[0].accepted_at = null;
  orders[0].production_started_at = null;
  orders[0].production_completed_at = null;
  orders[0].progress_entries = [];
}

module.exports = {
  getMockSupplyOrder,
  getMockSupplyOrders,
  resetMockSupplyOrders,
  runMockSupplyOrderAction
};
