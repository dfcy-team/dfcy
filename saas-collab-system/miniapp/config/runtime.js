"use strict";

// environment 可选值：development、test、preview、production。
// 真实构建应由受控流水线在制品生成阶段注入，禁止在此写入任何密钥。
module.exports = Object.freeze({
  environment: "development",
  apiBaseUrl:
    "https://conclusion-stadium-spam-geographical.trycloudflare.com",
  useMock: false,
  authMode: "platform"
});
