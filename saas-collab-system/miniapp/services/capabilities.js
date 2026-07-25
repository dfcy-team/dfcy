"use strict";

function getAuthCapability(config, context) {
  if (config.useMock) {
    return {
      status: "mock",
      description: "当前使用脱敏 Mock 会话。"
    };
  }
  if (context.authenticated) {
    return {
      status: "connected",
      description:
        config.authMode === "platform"
          ? "微信一次性登录凭证已由服务端完成交换并建立本地会话。"
          : "后端测试身份交换已完成并建立本地会话。"
    };
  }
  if (config.authMode === "sandbox") {
    return {
      status: "sandbox",
      description: "已配置后端沙箱身份交换，需预先绑定测试身份。"
    };
  }
  return {
    status: "pending",
    description: "等待后端 /api/miniapp/auth/* 专用端点完成身份交换。"
  };
}

function getFoundationCapabilities(config, context = {}) {
  const authCapability = getAuthCapability(config, context);
  return [
    {
      code: "engineering_foundation",
      name: "工程底座",
      status: "connected",
      description: "目录、环境、请求、会话、日志和页面状态已接入。"
    },
    {
      code: "miniapp_auth",
      name: "小程序认证",
      status: authCapability.status,
      description: authCapability.description
    },
    {
      code: "release_contract",
      name: "发布合同",
      status: config.useMock ? "mock" : "connected",
      description: config.useMock
        ? "只读工作台使用脱敏示例合同。"
        : "已接入服务端合同、状态机、门禁和只读查询。"
    },
    {
      code: "production_release",
      name: "真实平台发布",
      status: "disabled",
      description: "备案与微信平台审核完成前保持禁用；工程底座不自动执行真实平台发布。"
    }
  ];
}

module.exports = {
  getFoundationCapabilities
};
