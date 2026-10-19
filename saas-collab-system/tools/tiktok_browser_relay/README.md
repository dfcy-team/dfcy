# TK Browser Authorization Relay

This companion runs beside the existing DFCY public portal. It never exchanges a
TikTok authorization code, stores a marketplace token, or contacts the private
SaaS server. Browser navigation returns a signed, short-lived receipt to VM34.

## Installation Boundaries

- Copy `tiktok_saas_relay.py` and the exact reviewed
  `backend/apps/integrations/tiktok_bridge_protocol.py` beside the public app.
- Install the hook before the portal's existing public-route/login hooks:
  `install(app, key_file="/srv/dfcy-app/shared/tiktok-browser-relay/key")`.
- Do not expand the legacy public endpoint allowlist. Requests without an
  eligible TK flow continue through all original gates.
- Mount the same independent relay key read-only in VM34 and set
  `TIKTOK_BROWSER_BRIDGE_KEY_FILE`. Never reuse a marketplace App Secret.
- Both sides must have synchronized clocks. Only the fixed ROW TK authorization
  host and fixed VM34 return page are accepted.
- Approve the registered TK callback URI and authorization endpoint through the
  normal runtime configuration process; do not bypass network or approval gates.
- Redact callback queries from reverse-proxy access logs. The relay also removes
  intercepted query/RAW_URI values before WSGI access logging.

## Operation

One missing-state flow per browser is supported. A second different active flow
is rejected rather than replacing the first. Same-tab navigation preserves the
VM34 tab's existing SaaS login. No login tokens are copied to the public service.

If login expires, the tab is refreshed, or the network result is uncertain, check
the store authorization status before starting again. The original code must not
be retried automatically. Manual callback recovery is a separate legacy flow;
its in-memory nonce does not survive automatic same-tab navigation.

## Synthetic Tests

`python tools/tiktok_browser_relay/test_tiktok_saas_relay.py`

These tests use an isolated Flask application, placeholder keys and no network,
business database, or real marketplace credentials.
