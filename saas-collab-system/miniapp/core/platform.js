"use strict";

function requireWx() {
  if (typeof wx === "undefined") {
    throw new Error("WeChat runtime is unavailable.");
  }
  return wx;
}

function createWxTransport() {
  return function transport(options) {
    return new Promise((resolve, reject) => {
      requireWx().request({
        url: options.url,
        method: options.method,
        data: options.data,
        header: options.headers,
        timeout: options.timeout,
        success: resolve,
        fail: reject
      });
    });
  };
}

function createWxStorage() {
  return {
    get(key) {
      return requireWx().getStorageSync(key);
    },
    set(key, value) {
      requireWx().setStorageSync(key, value);
    },
    remove(key) {
      requireWx().removeStorageSync(key);
    }
  };
}

function platformLogin() {
  return new Promise((resolve, reject) => {
    requireWx().login({
      timeout: 8000,
      success(result) {
        if (!result.code) {
          reject(new Error("Platform login did not return a code."));
          return;
        }
        resolve(result.code);
      },
      fail: reject
    });
  });
}

module.exports = {
  createWxStorage,
  createWxTransport,
  platformLogin,
  requireWx
};
