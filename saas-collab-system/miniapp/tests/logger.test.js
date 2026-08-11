"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { redact } = require("../core/telemetry/logger");

test("logger recursively redacts credentials", () => {
  const redactedPassword = ["plain", "text"].join("-");
  const rowToken = ["row", "token"].join("-");
  const result = redact({
    authorization: "Bearer secret",
    nested: {
      password: redactedPassword,
      safe: "visible",
      session_key: "server-only"
    },
    rows: [{ token: rowToken }]
  });

  assert.equal(result.authorization, "***");
  assert.equal(result.nested.password, "***");
  assert.equal(result.nested.session_key, "***");
  assert.equal(result.nested.safe, "visible");
  assert.equal(result.rows[0].token, "***");
});

test("logger handles circular data", () => {
  const input = { safe: true };
  input.self = input;
  assert.equal(redact(input).self, "[Circular]");
});
