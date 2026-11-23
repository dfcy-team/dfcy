# TK Ads exchange diagnostics - 2026-10-31

## Confirmed outbound configuration blocker

New audit record 1080928 identifies exchange_token. A no-network invocation of assert_host_allowed for the official Marketing token endpoint fails with Outbound host is not approved. This is distinct from the approved callback allowlist. Prepared v36 (record 39), based on effective v35 (record 38), through create_config_version as actor 1. Only network.allowed_hosts gains business-api.tiktok.com; exact equality of all other fields was asserted. No modules field, no self approval. The draft remains pending approval by another authorized administrator. No old code was replayed. Provider exchange remains unverified until approval and one fresh user authorization attempt.

Scope: only backend/apps/integrations/tiktok_ads_oauth.py in Aliyun production-backend-1. No frontend, account, Shop authorization, sync task, or schema changes. This is a direct container hotfix, not a new image or merged PR.

The previous callback passed session validation but became unknown during exchange/custody. The old generic exception handler discarded the underlying stage. The historical cause remains unconfirmed. No old authorization code was replayed.

Changes: persist a random diagnostic ID and closed stage label in IntegrationAuditLog action ads_oauth_exchange_failure and backend logs. Include bounded numeric provider error code and HTTP status when available; never persist exception text, callback URL, auth code, secret or token. Keep unknown status and one-use exchange protections. Return diagnostic ID/stage in error response. Existing frontend still shows a generic warning, but operators can now locate the exact backend stage.

Verification: 64 isolated Ads direct/diagnostic tests passed; synthetic fixtures updated for the current runtime callback resolver. Live provider success is not claimed. Read-only custody operation reconciliation for the prior failure returned a provider error, not a confirmed missing token.

Backup: /opt/saas-collab/production/hotfix-tk-ads-diagnostics-20261031/before/tiktok_ads_oauth.py.
Deployed source: same directory under after/. Before SHA256: f743a95eb095419b37433085ff1d3caba69722334bf35508199e67ef3218d235.

Deployment uses py_compile, Django system check and graceful Gunicorn HUP. Preserve this narrow change when building the next image; container recreation from the old image will lose it. Roll back only this file from before/, check it, then gracefully reload workers. Preserve the separate 2026-10-30 Ads configuration hotfix and all unrelated live hotfixes.
