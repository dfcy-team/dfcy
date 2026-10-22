# TK web-managed direct callbacks

Production settings now exposes separate `shop_direct_callback_url` and
`ads_direct_callback_url` fields under the TikTok platform. They use the existing
version creation, independent administrator approval and rollback mechanism.
Draft values do not affect runtime. No migration or business-data import is needed.

After deploying this change:

1. Enter the Shop and Ads callbacks in Production Settings. Paths must be
   `/integrations/tiktok/shop-callback` and `/integrations/tiktok-ads/direct-callback`
   respectively, with HTTPS and no query, credentials or fragment.
2. Add each full URL to the OAuth redirect allowlist in the same configuration.
3. Have another authorized administrator approve the version.
4. Match each connection's callback and its corresponding TikTok app registration.
5. Start fresh authorization sessions. Do not replay old authorization codes.

Approved web values override deployment variables. Explicit empty values disable
the corresponding direct callback. Missing fields preserve deployment-variable
compatibility. Invalid effective configuration fails closed. Changing approved
configuration invalidates in-flight session fingerprints through existing guards.

This change does not approve platform contracts, change credentials, enable jobs,
register TikTok application callbacks or establish that real OAuth has succeeded.
