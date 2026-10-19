# Temporary TikTok Token Proxy

`LIVE_TIKTOK_TOKEN_PROXY_URL` is optional and disabled by default. It accepts only an unauthenticated HTTP loopback proxy and applies only to HTTPS `auth.tiktok-shops.com:443` at `/api/v2/token/get` and `/api/v2/token/refresh`. Custody, other platforms and other TK endpoints keep their existing routing. A configured proxy failure never falls back to another route. Existing zero-retry token exchange/refresh behavior is unchanged.

For a controlled VM34 test, SSH can reverse-forward a private Unix socket to the operator's local HTTP proxy. `relay.py` runs unprivileged in a dedicated container sharing the current backend network namespace, with only read-only relay-code and private-socket-directory mounts. Its listener is fixed to `127.0.0.1:17898`; CONNECT is restricted to `auth.tiktok-shops.com:443`. TLS is validated by the application end-to-end. No Docker socket, backend environment, application secret or token is supplied to the relay. No request or TLS payload logging is performed.

This is not a durable unattended deployment: Windows, the proxy and the SSH tunnel must stay online. Backend recreation requires re-binding the relay to the new backend container namespace. Do not delete an unknown forwarding socket or enable direct fallback when the tunnel is down. A managed fixed egress is preferable for long-term operation.

Do not replay a callback whose exchange timed out. Reconcile the authorization status first; obtain fresh authorization for the next attempt. Non-authentication HEAD/TLS probes only verify transport and do not prove successful token exchange.
