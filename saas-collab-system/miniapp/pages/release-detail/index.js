"use strict";

const { getReleaseContract } = require("../../services/releases");

Page({
  data: {
    contract: null,
    errorMessage: "",
    state: "loading"
  },

  onLoad(options) {
    this.contractId = options.id;
    this.loadContract();
  },

  async loadContract() {
    this.setData({ errorMessage: "", state: "loading" });
    const { client, config } = getApp().globalData.services;
    try {
      const data = await getReleaseContract(client, config, this.contractId);
      if (!data.read_only) {
        throw new Error("发布合同详情未声明只读边界");
      }
      this.setData({
        contract: data.contract,
        state: "ready"
      });
    } catch (error) {
      this.setData({
        errorMessage: error.message || "合同详情加载失败",
        state: "error"
      });
    }
  }
});
