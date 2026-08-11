"use strict";

const SENSITIVE_KEYS = new Set([
  "access",
  "access_token",
  "authorization",
  "cookie",
  "password",
  "refresh",
  "refresh_token",
  "secret",
  "session_key",
  "token"
]);

function redact(value, seen = new WeakSet()) {
  if (Array.isArray(value)) {
    return value.map((item) => redact(item, seen));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  if (seen.has(value)) {
    return "[Circular]";
  }
  seen.add(value);
  const output = {};
  Object.keys(value).forEach((key) => {
    output[key] = SENSITIVE_KEYS.has(key.toLowerCase())
      ? "***"
      : redact(value[key], seen);
  });
  return output;
}

function createLogger(options = {}) {
  const sink = options.sink || console;
  const context = options.context || {};

  function write(level, event, details = {}) {
    const record = redact({
      timestamp: new Date().toISOString(),
      level,
      event,
      ...context,
      ...details
    });
    const method = typeof sink[level] === "function" ? level : "log";
    sink[method](record);
    return record;
  }

  return {
    debug: (event, details) => write("debug", event, details),
    info: (event, details) => write("info", event, details),
    warn: (event, details) => write("warn", event, details),
    error: (event, details) => write("error", event, details)
  };
}

module.exports = {
  SENSITIVE_KEYS,
  createLogger,
  redact
};
