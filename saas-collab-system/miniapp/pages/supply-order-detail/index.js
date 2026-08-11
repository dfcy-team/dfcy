"use strict";

const {
  getSupplyOrder,
  runSupplyOrderAction
} = require("../../services/supply-chain");

const STATUS_LABELS = {
  pending: "待接单",
  accepted: "已接单",
  in_production: "生产中",
  production_completed: "生产完成"
};

const ACTION_LABELS = {
  accept: "确认接单",
  "start-production": "开始生产",
  "complete-production": "确认生产完成"
};

Page({
  data: {
    completedQuantity: 0,
    errorMessage: "",
    note: "",
    order: null,
    state: "loading",
    submitting: false
  },

  onLoad(options) {
    this.orderId = options.id;
  },

  onShow() {
    if (this.orderId) this.loadOrder();
  },

  async loadOrder() {
    this.setData({ errorMessage: "", state: "loading" });
    const { client, config } = getApp().globalData.services;
    try {
      const order = await getSupplyOrder(client, config, this.orderId);
      this.setData({
        completedQuantity: Number(order.completed_quantity || 0),
        order: {
          ...order,
          progress_percent: order.total_quantity
            ? Math.round((Number(order.completed_quantity) / Number(order.total_quantity)) * 100)
            : 0,
          status_label: STATUS_LABELS[order.status] || order.status
        },
        state: "ready"
      });
    } catch (error) {
      this.setData({
        errorMessage: error.message || "采购单详情加载失败",
        state: "error"
      });
    }
  },

  onQuantityInput(event) {
    this.setData({ completedQuantity: Number(event.detail.value || 0) });
  },

  onNoteInput(event) {
    this.setData({ note: event.detail.value || "" });
  },

  async confirmAction(event) {
    const action = event.currentTarget.dataset.action;
    const label = ACTION_LABELS[action];
    const confirmation = await new Promise((resolve) => {
      wx.showModal({
        title: "确认业务动作",
        content: `${label}？该动作会写入本地审计记录。`,
        success: (result) => resolve(Boolean(result.confirm)),
        fail: () => resolve(false)
      });
    });
    if (confirmation) await this.submitAction(action, {});
  },

  async submitProgress() {
    const order = this.data.order;
    const quantity = Number(this.data.completedQuantity);
    if (quantity < Number(order.completed_quantity) || quantity > Number(order.total_quantity)) {
      wx.showToast({ title: "进度数量不合法", icon: "none" });
      return;
    }
    await this.submitAction("update-progress", {
      completed_quantity: quantity,
      note: this.data.note
    });
  },

  async submitAction(action, payload) {
    this.setData({ submitting: true });
    const { client, config } = getApp().globalData.services;
    try {
      const result = await runSupplyOrderAction(
        client,
        config,
        this.orderId,
        action,
        payload
      );
      wx.showToast({
        title: result.replayed ? "已复用原结果" : "操作成功",
        icon: "success"
      });
      await this.loadOrder();
    } catch (error) {
      wx.showToast({ title: error.message || "操作失败", icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  }
});
