"use strict";

const { getSupplyOrders } = require("../../services/supply-chain");

const STATUS_LABELS = {
  pending: "待接单",
  accepted: "已接单",
  in_production: "生产中",
  production_completed: "生产完成"
};

Page({
  data: {
    errorMessage: "",
    hasMore: false,
    loadingMore: false,
    orders: [],
    page: 1,
    pageSize: 20,
    state: "loading",
    total: 0
  },

  onShow() {
    this.loadOrders();
  },

  onReachBottom() {
    this.loadMore();
  },

  loadOrders() {
    this.setData({ page: 1 });
    return this.fetchOrders(false);
  },

  loadMore() {
    if (!this.data.hasMore || this.data.loadingMore) {
      return Promise.resolve();
    }
    this.setData({ page: this.data.page + 1 });
    return this.fetchOrders(true);
  },

  async fetchOrders(append) {
    this.setData({
      errorMessage: "",
      loadingMore: append,
      state: append ? this.data.state : "loading"
    });
    const { client, config } = getApp().globalData.services;
    try {
      const data = await getSupplyOrders(client, config, {
        page: this.data.page,
        page_size: this.data.pageSize
      });
      const pageOrders = (data.results || []).map((order) => ({
        ...order,
        progress_percent: order.total_quantity
          ? Math.round((Number(order.completed_quantity) / Number(order.total_quantity)) * 100)
          : 0,
        status_label: STATUS_LABELS[order.status] || order.status
      }));
      const orders = append ? this.data.orders.concat(pageOrders) : pageOrders;
      const total = Number(data.count || 0);
      this.setData({
        hasMore: orders.length < total && pageOrders.length > 0,
        loadingMore: false,
        orders,
        state: orders.length ? "ready" : "empty",
        total
      });
    } catch (error) {
      this.setData({
        errorMessage: error.message || "供应链采购单加载失败",
        loadingMore: false,
        state: "error"
      });
    }
  },

  openOrder(event) {
    const id = event.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/supply-order-detail/index?id=${id}` });
  }
});
