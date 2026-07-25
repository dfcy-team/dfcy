"use strict";

const {
  getMockSupplyOrder,
  getMockSupplyOrders,
  runMockSupplyOrderAction
} = require("../mock/supply-chain");

async function getSupplyOrders(client, config, params = {}) {
  if (config.useMock) {
    return getMockSupplyOrders(params);
  }
  return client.request({
    method: "GET",
    path: "/api/miniapp/supply-chain/orders/",
    data: params
  });
}

async function getSupplyOrder(client, config, id) {
  if (config.useMock) {
    return getMockSupplyOrder(id);
  }
  return client.request({
    method: "GET",
    path: `/api/miniapp/supply-chain/orders/${id}/`
  });
}

async function runSupplyOrderAction(client, config, id, action, payload = {}) {
  if (config.useMock) {
    return runMockSupplyOrderAction(id, action, payload);
  }
  return client.request({
    method: "POST",
    path: `/api/miniapp/supply-chain/orders/${id}/actions/${action}/`,
    data: payload
  });
}

module.exports = {
  getSupplyOrder,
  getSupplyOrders,
  runSupplyOrderAction
};
