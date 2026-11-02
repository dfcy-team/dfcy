# Developer application API contract

All console endpoints use the authenticated internal session and return the standard `{ "success": true, "code": "OK", "message": "success", "data": ... }` envelope. Application records and logs are tenant-scoped; developers may access only applications they created. Approvers are separate internal API approvers and cannot approve an application they created or last edited.

Navigation: 授权中心 → 开发者中心 → 内部开发对接. Existing 内部系统数据接口 remains unchanged.

## Console endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /api/internal/integrations/developer-apps/` | List current developer's apps and selectable connection/account catalog |
| `POST /api/internal/integrations/developer-apps/` | Submit application. Body: `{name, description, endpoint_ids:[1,2], expires_at}`. Endpoints may span multiple platform connections/accounts. |
| `PATCH /api/internal/integrations/developer-apps/{id}/` | Request changes. Body: `{name?,description?,endpoint_ids?,expires_at?}`. Newly requested endpoints remain pending; existing approved endpoint grants remain usable while review is pending. |
| `GET /api/internal/integrations/developer-apps/{id}/` | App details, requested/approved endpoints, status, expiry, and one-time documentation links. |
| `POST /api/internal/integrations/developer-apps/{id}/review/` | Approver only. Body: `{decision:"approve"|"reject", reason?}`. |
| `POST /api/internal/integrations/developer-apps/{id}/token/` | Issue/replace a token after approval. Secret appears once in response. |
| `POST /api/internal/integrations/developer-apps/{id}/revoke/` | Revoke token and disable app. |
| `GET /api/internal/integrations/developer-apps/{id}/logs/` | Tenant and owner-scoped access/request audit list; secrets are never returned. |
| `GET /api/internal/integrations/developer-catalog/` | Returns `{connections:[{id,platform,name}],accounts:[{id,connection_id,name}],endpoints:[{id,code,name,connection_id,account_id,method,path,auth_mode}]}`. Only approved, callable endpoint definitions appear. |
| `POST /api/internal/integrations/developer-catalog/` | Admin-register an endpoint against an existing connection/account. Body: `{connection_id, account_id, code, name, method, path, auth_mode}`. Only supported safe auth modes are accepted; arbitrary destination URLs are not. |
| `GET /api/internal/integrations/developer-apps/{id}/docs/` | Download generated OpenAPI JSON and executable examples; these contain no credentials. |

Successful application submission returns `201` and `{id,status:"pending",approval_status:"pending",endpoints:[...]}`. A reviewer response returns `{id,status:"active"|"disabled",approval_status:"approved"|"rejected"}`. Token issue returns `{token,token_display_once:true,expires_at}`. The gateway authenticates `Authorization: Bearer <token>` and accepts `POST /api/developer-gateway/v1/{app_id}/{endpoint_code}/` with `{query:{...},body:{...}}`; only approved endpoint codes execute. Gateway replies `{data:...,request_id:...}` or an HTTP error. Calls are rate-limited and logged without request secrets.

`GET /api/internal/integrations/developer-apps/{id}/docs/` returns a ZIP archive (`application/zip`) with an OpenAPI 3.1 JSON document describing approved endpoint paths, containing language-neutral curl examples and Python/JavaScript examples. Both artifacts include bearer-token placeholders only, never a credential value.

Application edits update requested_endpoint_ids and requested_expires_at only. Existing approved grants and expiry remain effective during review or rejection. Approval atomically replaces the effective grant set. Tokens never authorize an endpoint beyond the app's currently approved endpoint set. Expired or revoked tokens fail closed.

Implementation limits: bearer and X-API-Key adapters use server custody access-token references. TikTok Shop and Shopee shop-signature adapters plus Lazada GET signing are included, reusing existing signing helpers. Other identity modes, multipart uploads and additional platform protocols require a platform-specific adapter. Connection network_enabled and active or verified status are required; writes require sandbox and sync_write_enabled. DNS must resolve only to public IPs, connections pin the verified IP and retain TLS hostname verification. Maximum request is 64 KiB, response 1 MiB, no retries or redirects. Console logs return latest 200 records. Developer tokens use app-id.secret and are never included in documentation archives.
