"use strict";

const { AppError, AuthError, NetworkError } = require("../errors");

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function createRequestId() {
  return `mp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function joinUrl(baseUrl, path) {
  return `${String(baseUrl).replace(/\/+$/, "")}/${String(path).replace(/^\/+/, "")}`;
}

function normalizeEnvelope(body, statusCode, requestId) {
  if (
    body &&
    typeof body === "object" &&
    typeof body.success === "boolean" &&
    Object.prototype.hasOwnProperty.call(body, "data")
  ) {
    if (body.success) {
      return body.data;
    }
    throw new AppError(body.message || "请求处理失败", {
      code: body.code || "API_ERROR",
      statusCode,
      requestId,
      details: body.data || null,
      retryable: statusCode >= 500
    });
  }
  throw new AppError("服务端响应不符合小程序 API 合同", {
    code: "INVALID_RESPONSE_ENVELOPE",
    statusCode,
    requestId
  });
}

function createRequestClient(options) {
  const {
    getConfig,
    logger,
    refreshSession,
    session,
    transport
  } = options;
  if (!transport || !session || !getConfig) {
    throw new Error("transport, session and getConfig are required.");
  }
  let refreshPromise = null;

  async function refreshAccessToken() {
    if (!refreshSession) {
      throw new AuthError();
    }
    if (!refreshPromise) {
      refreshPromise = Promise.resolve()
        .then(() => refreshSession())
        .finally(() => {
          refreshPromise = null;
        });
    }
    return refreshPromise;
  }

  async function request(input, attempt = 0) {
    const config = getConfig();
    const method = String(input.method || "GET").toUpperCase();
    const requestId = input.requestId || createRequestId();
    const headers = {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Request-ID": requestId,
      "X-Client-Version": "miniapp-foundation/0.1.0",
      ...(input.headers || {})
    };

    if (input.auth !== false) {
      const token = session.getAccessToken();
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
    }
    if (!SAFE_METHODS.has(method) && !headers["Idempotency-Key"]) {
      headers["Idempotency-Key"] = requestId;
    }

    logger?.debug("api.request", {
      method,
      path: input.path,
      requestId
    });

    let response;
    try {
      response = await transport({
        data: input.data,
        headers,
        method,
        timeout: input.timeout || config.requestTimeoutMs,
        url: joinUrl(config.apiBaseUrl, input.path)
      });
    } catch (error) {
      logger?.warn("api.network_error", {
        method,
        path: input.path,
        requestId,
        reason: error?.errMsg || error?.message || "unknown"
      });
      if (SAFE_METHODS.has(method) && attempt === 0 && input.retry !== false) {
        return request({ ...input, requestId }, attempt + 1);
      }
      throw new NetworkError("网络异常，请稍后重试", {
        requestId,
        details: { reason: error?.errMsg || error?.message || "unknown" }
      });
    }

    const statusCode = Number(response.statusCode || 0);
    if (statusCode === 401 && input.auth !== false && attempt === 0) {
      try {
        await refreshAccessToken();
        return request({ ...input, requestId }, attempt + 1);
      } catch (error) {
        session.clear();
        throw error instanceof AuthError ? error : new AuthError();
      }
    }

    if (statusCode < 200 || statusCode >= 300) {
      const body = response.data || {};
      throw new AppError(body.message || `请求失败（HTTP ${statusCode}）`, {
        code: body.code || `HTTP_${statusCode}`,
        statusCode,
        requestId,
        details: body.data || null,
        retryable: statusCode >= 500
      });
    }

    const data = normalizeEnvelope(response.data, statusCode, requestId);
    logger?.info("api.response", {
      method,
      path: input.path,
      requestId,
      statusCode
    });
    return data;
  }

  return {
    request
  };
}

module.exports = {
  createRequestClient,
  createRequestId,
  joinUrl,
  normalizeEnvelope
};
