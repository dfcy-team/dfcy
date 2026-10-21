# XTSY TikTok Direct Integration, V2.44.272

Base: `3e304ff4e717c520049431236c81b1b0e3aa4f0c`, verified against the running
cloud backend image revision on 2026-10-21. The older V1.0 operating manual
describes V2.44.262 and must not override current deployment evidence.

## Intended Routes

- Shop: browser -> official TikTok seller authorization -> XTSY Shop callback.
- Ads: browser -> official TikTok Ads authorization -> XTSY Ads callback.
- Token exchange, renewal and data collection: XTSY backend/worker -> official
  TikTok HTTPS API -> XTSY database -> XTSY reports.
- Developer credentials remain in the existing XTSY custody service. It does
  not relay platform API requests. Shop and Ads retain separate applications.

No main-site/AWS receipt relay, cloud-to-VM34 forwarding, HTTP CONNECT proxy,
or proxy fallback is used for the supported TK official API hosts.
Other platforms retain their existing transport selection.

## Configuration To Apply During Coordinated Cutover

These are proposed values, not a statement that production has changed.

| Item | Target |
| --- | --- |
| Shop configuration | Existing cloud config 34, keep its App Key and Service ID |
| Shop callback and TIKTOK_SHOP_DIRECT_CALLBACK_URL | https://xtsy.dingfengchuangyu.com/integrations/tiktok/shop-callback |
| Ads configuration | Existing cloud config 33, keep its separate App ID |
| Ads callback, per-config redirect_uri and TIKTOK_ADS_DIRECT_CALLBACK_URL | https://xtsy.dingfengchuangyu.com/integrations/tiktok-ads/direct-callback |
| Shop runtime auth_url, ROW auth_urls | https://services.tiktokshop.com/open/authorize |
| Shop runtime redirect_uri | Shop callback above |
| Shop API host | https://open-api.tiktokglobalshop.com |
| Shop token host | https://auth.tiktok-shops.com |
| Ads API host | https://business-api.tiktok.com |
| Runtime callback allowlist | Add both exact callback URLs; preserve unrelated entries |

Publish runtime changes through the existing configuration approval workflow.
Do not put secrets or tokens in runtime JSON. Enable Ads read/network admission
only with its approved configuration; do not enable schedules as a side effect.
Keep write capabilities disabled.

Both corresponding TikTok application registrations must use the exact new
callback before live authorization acceptance. A callback to the XTSY home page
or to dingfengchuangyu.com/callback is not a direct callback for this release.
Both automatic navigation and manual pasted URLs must use the registered URL.
Manual input parses a URL; it never fetches it or bypasses ownership checks.

## Deployment Boundaries

Deploy backend, worker code, custody operation support, frontend and callback
Nginx headers together. Apply only integrations 0050/0051 after existing 0049
Feishu reminders. Preserve all existing cloud business data and credentials.
Before applying changes, snapshot current schemas/configuration and inspect
in-flight jobs/grants affected by configuration digests. Never replay codes or
overwrite existing authorization evidence to make a new configuration pass.

First-time Shop binding discovers actual authorized stores and asks for an
explicit selection; it does not require a prefilled platform ID. Ads accounts
are independently checked and may be bound many-to-one to a store. Binding is
not proof of successful data ingestion. Verify a small complete report window
before enabling schedules, and distinguish BASIC spend from GMV Max.

## Verification Scope

Synthetic tests and a production build are not live OAuth acceptance. Current
cloud code did not contain the new callbacks at initial inspection. Direct
TCP/TLS to all three API hosts succeeded from the cloud backend without using
credentials or making HTTP API requests. Production activation remains a
separate deployment and application-registration step.
