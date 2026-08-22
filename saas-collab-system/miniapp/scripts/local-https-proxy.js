"use strict";

const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");

const listenHost = process.env.LOCAL_HTTPS_HOST || "127.0.0.1";
const listenPort = Number(process.env.LOCAL_HTTPS_PORT || 9444);
const upstreamHost = process.env.LOCAL_API_HOST || "127.0.0.1";
const upstreamPort = Number(process.env.LOCAL_API_PORT || 8002);
const certificateDirectory =
  process.env.LOCAL_HTTPS_CERT_DIR || path.resolve(__dirname, "..", ".certs");
const keyPath = path.join(certificateDirectory, "localhost-key.pem");
const certificatePath = path.join(certificateDirectory, "localhost.pem");

for (const requiredPath of [keyPath, certificatePath]) {
  if (!fs.existsSync(requiredPath)) {
    console.error(`Missing local HTTPS certificate file: ${requiredPath}`);
    console.error("Generate the trusted local certificate before starting this proxy.");
    process.exit(1);
  }
}

const server = https.createServer(
  {
    key: fs.readFileSync(keyPath),
    cert: fs.readFileSync(certificatePath),
    minVersion: "TLSv1.2"
  },
  (request, response) => {
    const headers = {
      ...request.headers,
      host: `${upstreamHost}:${upstreamPort}`,
      "x-forwarded-host": request.headers.host || `${listenHost}:${listenPort}`,
      "x-forwarded-proto": "https"
    };

    const upstream = http.request(
      {
        hostname: upstreamHost,
        port: upstreamPort,
        method: request.method,
        path: request.url,
        headers
      },
      (upstreamResponse) => {
        response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
        upstreamResponse.pipe(response);
      }
    );

    upstream.setTimeout(15000, () => {
      upstream.destroy(new Error("Local API upstream timed out."));
    });
    upstream.on("error", (error) => {
      if (!response.headersSent) {
        response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
      }
      response.end(
        JSON.stringify({
          success: false,
          code: "LOCAL_HTTPS_UPSTREAM_UNAVAILABLE",
          message: error.message
        })
      );
    });
    request.pipe(upstream);
  }
);

server.on("error", (error) => {
  console.error(`Local HTTPS proxy failed: ${error.message}`);
  process.exitCode = 1;
});

server.listen(listenPort, listenHost, () => {
  console.log(
    `Local HTTPS API listening at https://${listenHost}:${listenPort} -> ` +
      `http://${upstreamHost}:${upstreamPort}`
  );
});
