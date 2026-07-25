"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  getSupplyOrder,
  getSupplyOrders,
  runSupplyOrderAction
} = require("../services/supply-chain");
const { resetMockSupplyOrders } = require("../mock/supply-chain");

test.beforeEach(() => {
  resetMockSupplyOrders();
});

test("development mock exposes only supplier-safe purchase order fields", async () => {
  const data = await getSupplyOrders(null, { useMock: true });
  assert.equal(data.count, 1);
  assert.equal(data.results[0].status, "pending");
  const serialized = JSON.stringify(data);
  assert.doesNotMatch(serialized, /unit_price|source_payload_hash|service.?role/i);
});

test("service uses only the dedicated miniapp supply-chain boundary", async () => {
  const requests = [];
  const client = {
    request(input) {
      requests.push(input);
      return Promise.resolve({ ok: true });
    }
  };
  const config = { useMock: false };

  await getSupplyOrders(client, config, { page: 2, page_size: 20 });
  await getSupplyOrder(client, config, 101);
  await runSupplyOrderAction(
    client,
    config,
    101,
    "update-progress",
    { completed_quantity: 8 }
  );

  assert.deepEqual(
    requests.map((item) => `${item.method} ${item.path}`),
    [
      "GET /api/miniapp/supply-chain/orders/",
      "GET /api/miniapp/supply-chain/orders/101/",
      "POST /api/miniapp/supply-chain/orders/101/actions/update-progress/"
    ]
  );
  assert.deepEqual(requests[0].data, { page: 2, page_size: 20 });
  assert.doesNotMatch(JSON.stringify(requests), /supabase|mysql|api\.weixin|service.?role/i);
});

test("mock list honors page and page_size", async () => {
  const first = await getSupplyOrders(null, { useMock: true }, { page: 1, page_size: 1 });
  const second = await getSupplyOrders(null, { useMock: true }, { page: 2, page_size: 1 });

  assert.equal(first.count, 1);
  assert.equal(first.results.length, 1);
  assert.equal(second.results.length, 0);
});

test("mock SC-F1 workflow accepts, starts, reports progress and completes", async () => {
  const config = { useMock: true };

  assert.equal(
    (await runSupplyOrderAction(null, config, 9001, "accept")).order.status,
    "accepted"
  );
  assert.equal(
    (await runSupplyOrderAction(null, config, 9001, "start-production")).order.status,
    "in_production"
  );
  const progress = await runSupplyOrderAction(
    null,
    config,
    9001,
    "update-progress",
    { completed_quantity: 100, note: "本地完成" }
  );
  assert.equal(progress.order.completed_quantity, 100);
  assert.equal(progress.order.progress_entries.length, 1);
  assert.equal(
    (await runSupplyOrderAction(null, config, 9001, "complete-production")).order.status,
    "production_completed"
  );
});

test("mock rejects progress above the purchase order total", async () => {
  const config = { useMock: true };
  await runSupplyOrderAction(null, config, 9001, "accept");
  await runSupplyOrderAction(null, config, 9001, "start-production");

  await assert.rejects(
    runSupplyOrderAction(
      null,
      config,
      9001,
      "update-progress",
      { completed_quantity: 101 }
    ),
    /不能超过采购数量/
  );
});
