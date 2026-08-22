"use strict";

class AppError extends Error {
  constructor(message, options = {}) {
    super(message || "操作失败");
    this.name = options.name || "AppError";
    this.code = options.code || "APP_ERROR";
    this.statusCode = options.statusCode || 0;
    this.requestId = options.requestId || "";
    this.details = options.details || null;
    this.retryable = Boolean(options.retryable);
  }
}

class AuthError extends AppError {
  constructor(message = "登录状态已失效", options = {}) {
    super(message, {
      ...options,
      name: "AuthError",
      code: options.code || "AUTH_INVALID"
    });
  }
}

class NetworkError extends AppError {
  constructor(message = "网络连接不可用", options = {}) {
    super(message, {
      ...options,
      name: "NetworkError",
      code: options.code || "NETWORK_ERROR",
      retryable: options.retryable !== false
    });
  }
}

module.exports = {
  AppError,
  AuthError,
  NetworkError
};
