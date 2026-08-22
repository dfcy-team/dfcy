"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createRequestClient } = require("../core/request/client");

function createSession() {
  let accessToken = "old-access";
  return {
    clear() {
      accessToken = "";
    },
    getAccessToken: () => accessToken,
    setAccessToken: (value) => {
      accessToken = value;
    }
  };
}

const getConfig = () => ({
  apiBaseUrl: "https://api.example.invalid",
  requestTimeoutMs: 1000
});

test("request unwraps the unified response envelope", async () => {
  const client = createRequestClient({
    getConfig,
    session: createSession(),
    transport: async (options) => {
      assert.equal(options.headers.Authorization, "Bearer old-access");
      assert.match(options.headers["X-Request-ID"], /^mp-/);
      return {
        statusCode: 200,
        data: {
          success: true,
          code: "OK",
          message: "",
          data: { id: 1 }
        }
      };
    }
  });

  assert.deepEqual(await client.request({ path: "/api/miniapp/example/" }), { id: 1 });
});

test("write request receives an idempotency key", async () => {
  const client = createRequestClient({
    getConfig,
    session: createSession(),
    transport: async (options) => {
      assert.equal(
        options.headers["Idempotency-Key"],
        options.headers["X-Request-ID"]
      );
      return {
        statusCode: 200,
        data: { success: true, data: { saved: true } }
      };
    }
  });
  const result = await client.request({
    method: "POST",
    path: "/api/miniapp/example/",
    data: { name: "demo" }
  });
  assert.equal(result.saved, true);
});

test("401 refreshes once and retries with the new token", async () => {
  const session = createSession();
  let calls = 0;
  let refreshCalls = 0;
  const client = createRequestClient({
    getConfig,
    session,
    refreshSession: async () => {
      refreshCalls += 1;
      session.setAccessToken("new-access");
    },
    transport: async (options) => {
      calls += 1;
      if (calls === 1) {
        assert.equal(options.headers.Authorization, "Bearer old-access");
        return { statusCode: 401, data: { message: "expired" } };
      }
      assert.equal(options.headers.Authorization, "Bearer new-access");
      return {
        statusCode: 200,
        data: { success: true, data: { refreshed: true } }
      };
    }
  });

  const result = await client.request({ path: "/api/miniapp/protected/" });
  assert.equal(result.refreshed, true);
  assert.equal(refreshCalls, 1);
  assert.equal(calls, 2);
});

test("invalid success response is rejected", async () => {
  const client = createRequestClient({
    getConfig,
    session: createSession(),
    transport: async () => ({
      statusCode: 200,
      data: { result: "legacy" }
    })
  });
  await assert.rejects(
    client.request({ path: "/api/miniapp/legacy/" }),
    /不符合小程序 API 合同/
  );
});
