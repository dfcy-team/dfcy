# TK Shop and Ads Direct Authorization

## Scope

Both TK entry methods (official authorization navigation and pasted callback
URL) terminate in the same SaaS deployment. Neither method fetches the pasted
URL or uses the main-site/AWS relay. Shopee, Lazada and Jifeng are unchanged.
Legacy relay receipts are not accepted for live authorization.

This document is a local implementation handoff, not a production acceptance
receipt. No TikTok application registration, VM34 or Aliyun settings are changed
by adding these files.

After this original handoff, the user separately approved a fresh isolated VM34
test deployment at `https://192.168.2.34:9443`. The old 8443 stack and Aliyun were
not changed. Its deployment receipt is
`operations/tiktok-direct-v263-deploy-20261020/DEPLOYMENT.md`; do not confuse this
test deployment with a live-platform or cloud-production acceptance.

## Callback Configuration

Use the deployment's own HTTPS origin for both addresses:

- Shop: `TIKTOK_SHOP_DIRECT_CALLBACK_URL=https://<saas-origin>/integrations/tiktok/shop-callback`
- Ads: `TIKTOK_ADS_DIRECT_CALLBACK_URL=https://<saas-origin>/integrations/tiktok-ads/direct-callback`

The user selected these final cloud addresses (not applied by this task):

- `https://xtsy.dingfengchuangyu.com/integrations/tiktok/shop-callback`
- `https://xtsy.dingfengchuangyu.com/integrations/tiktok-ads/direct-callback`

VM34 is only an isolated acceptance environment. Do not update its live stack,
point the cloud domain at VM34, or edit the live TikTok registration as part of
this local implementation task.

Shop and Ads belong to different TikTok authorization products. Their app
configuration, callback registration and credentials must not be mixed. Each
callback must exactly match its selected integration configuration and the
approved runtime OAuth redirect allowlist. An empty or invalid direct setting
fails closed; there is no relay fallback. The developer-secret reference and
normal live-network/read-only gates remain required.

For VM34, browser access to a LAN address does not establish that TikTok accepts
that address as an application's callback. Verify the final HTTPS address,
certificate, app registration and browser access before cutover. Do not change
the shared TikTok app callback while another environment still depends on the
old registration. Use independent apps or an agreed coordinated cutover.

## User Flow

1. In the store API dialog choose the Shop or Ads configuration.
2. Start authorization in the same tab, or prepare the manual callback form.
3. The tab creates a random verifier; only its digest is saved server-side.
4. TikTok returns to the dedicated SaaS callback. Query material is removed
   before router startup. A signed actor/tenant/target-bound token and the tab
   verifier are required by the authenticated one-shot completion POST.
5. Shop with no external ID: exchange once, discover real shops, display only
   name/ID/country, explicitly choose one, then confirm. Store ID backfill and
   authorization save commit atomically. Even one candidate requires confirmation.
6. Ads: exchange once, discover accessible advertisers, validate selected accounts
   and bind multiple accounts through the existing independent Ads session.
7. Neither authorization nor binding starts a report import or enables sync.

Pasted URLs must be the exact registered callback on the same SaaS origin.
They are parsed locally, never fetched. Duplicate or foreign parameters are
rejected. The manual form uses the same one-shot completion endpoint as automatic
navigation, not the old recovery endpoint.

For manual authorization in a separate tab, the callback page has no originating
tab proof and does not exchange the code. It removes the query immediately and
offers an explicit copy action. The callback exists only in memory until copied
or the page is left; paste it into the prepared form in the original SaaS tab.
Reloading that unproven tab cannot recover the code or trigger an exchange.

## Failures and Recovery

- Unknown Shop ID requires the state actually returned by TikTok. A checkbox,
  region or pasted URL does not independently establish ownership.
- Wrong, empty, stale or another actor's state/verifier is rejected before exchange.
- A timed-out/ambiguous exchange is not retried. Inspect persisted session and
  authorization status before starting a new authorization.
- The Shop confirmation page can be reloaded by its non-secret binding UUID.
  Refresh reads the pending result; it never exchanges the code again.
- Confirmation is idempotent for the same selection, rejects a different
  selection, rechecks permissions/configuration and preserves DB uniqueness.
- Cancelled/expired Shop staging is processed by the bounded cleanup task on
  the credential-refresh queue. The custody sidecar must include the authenticated
  `/tokens/operation` endpoint. Closing an operation permanently fences delayed
  custody writes, including a crash before references were saved to the SaaS row.
- Cleanup never revokes references already owned by any saved authorization,
  regardless of authorization status. Unconfirmed cleanup stays pending for retry.
- Known-Shop reauthorization also stages its new references durably. Old references
  have a transactional cleanup outbox, separate from the new bound operation;
  failed or lost post-commit cleanup is retried with a lease and fence.
- Ads response loss or a crash after custody storage is reconciled by its stable
  operation ID. Expired sessions remain readable without replaying a code.

## Deployment Gates

- Review final local diff and run focused, security and non-TK regression tests.
- Run migration drift check and apply the additive migration to a disposable DB.
- Verify MySQL locking/uniqueness against a disposable MySQL instance separately;
  SQLite passing is not a MySQL concurrency acceptance result.
- Build frontend and check permission registry consistency.
- Upgrade the custody sidecar before enabling either Shop or Ads operation cleanup.
- Ensure the public web server does not log callback query strings and emits
  `Cache-Control: no-store` and `Referrer-Policy: no-referrer` on callback pages.
- Back up database schema/data, verify the deployed revision and migration graph,
  then stage only the approved release. Do not overwrite shared live worktrees.
- Change TikTok callback registrations only after code and configuration are ready;
  perform one fresh Shop and one fresh Ads authorization for browser/runtime
  acceptance. Do not reuse authorization codes from chat or historic screenshots.

The existing VM34 image was used only as an isolated dependency runtime. Missing
test dependencies were mounted read-only in the temporary runner, never installed
into a live container. A release must build its own image from the checked-in
requirements; it must not depend on those test mounts.

## Frozen Local Evidence

Target: branch `fix/tiktok-postauth-shop-binding-20261020`, base/HEAD
`30b3bde4095581c711f5c03b58aab6b90a0eda22` plus the explicitly reviewed local diff.
This is not a claim about a remote branch or deployed revision.

- Independent code review: zero remaining P0/P1/P2 findings on the 55-file code
  snapshot. The operation-recovery, old-reference outbox and manual-tab handoff
  findings were re-reviewed after their fixes.
- Network-denied backend regression: 349 passed, 4 skipped, 353 collected.
  `backend-freeze.xml` records the exact cases. Skips cover a separate MySQL-only
  historical recovery probe and three platform-dependent custody checks.
- Django system check passed; migration drift check reported no changes.
- Frontend: 156 Vitest tests and 15 Node tests passed; build passed; menu/route
  registry and authorization-surface checks passed. Exact commands and logs are
  under `frontend/validation-logs/frontend-freeze-20261020-120704`.
- Final independent isolated MySQL run: 171 passed, zero failed/skipped,
  including three concurrency cases and the actual 0049/0050 migration probe.
  Execution evidence is recorded in the independent test report under
  `operations/tiktok-postauth-20261020`. The four temporary containers, test
  network and remote staging path were then removed; live VM34 was unchanged.
- Shared/non-TK regression: 51 passed, two explicit Shopee-only parameter skips.

No live TikTok authorization, token exchange, business import, scheduling change
or production migration/deployment was performed. Live browser acceptance is not
covered by the focused tests. The separately approved isolated deployment added
the complete fresh-MySQL migration evidence described below.

## Historical Baseline Blocker And Approved Repair

Full fresh MySQL migration of the current mainline fails in the unchanged
`development.0002_product_sales_summary_view`: its `RunPython` issues view DDL
inside an atomic migration on MySQL, which raises `TransactionManagementError`.
This was initially outside the TK-only scope and was not changed during the
first handoff. The user subsequently explicitly approved the minimal repair:
`RunPython(..., atomic=False)`, leaving view SQL and migration state unchanged.
The independent VM34 9443 database then applied all 367 migrations from empty,
without fake/history edits or production data copies. The transaction guard and
corrected synthetic MySQL regression passed. This proves fresh bootstrap of the
tested candidate, not an in-place upgrade of the older divergent live databases.

## API Contract Source

TikTok's [application setup documentation](https://partner.us.tiktokshop.com/docv2/page/create-your-app)
distinguishes seller authorization from token exchange and recommends checking
the token/shop mapping using Get Authorized Shops. The implementation keeps
provider calls server-side and returns only safe candidate metadata to the browser.

## Current VM34 Integration Candidate

This candidate ports the preserved draft onto the current VM34 base
`d6acb9de7159c80dc85c93c99f9070ea1038a616`, retaining the separately approved
warehouse mixed-scope read compatibility fix. It does not include the later
unrelated V2.44.266 changes. The original V263 worktree remains unchanged.

The human approved eventual deployment to VM34 port 8443 after review and tests.
The latest clarification supersedes the earlier independent-app assumption:
only the original shared Shop and Ads applications exist. The selected next step
is isolated VM34 acceptance, preserving original registrations and configurations;
coordinate real direct callbacks later on the cloud SaaS. Existing configurations
7 and 8 and their credentials remain unchanged. App Secrets belong in credential
custody, not chat or Git. Publishing code is not live OAuth acceptance.

The current integration adds regression protection for:

- Ads official callbacks may include optional `id`; it must match the selected
  app ID before any claim or secret access. `auth_code` is authoritative when
  both `auth_code` and `code` exist; duplicate query keys remain rejected.
- Both dedicated callback paths have explicit route-capability registrations
  using the existing authorization permission, without adding role grants.
- Shopee keeps its platform-specific missing-callback guidance; TK uses its own
  direct-configuration messages.
- Merely enabling independent-app callback settings does not change historical
  TK configuration fingerprints whose callbacks are not those direct endpoints.
  Each new direct flow is fenced only by its own product's callback setting.
  This does not bypass the existing global runtime-version invalidation rule:
  an approved runtime-policy change can still require normal revalidation.
- Direct callback expectation is selected by the TK configuration's API type,
  using the same exact-match policy for readiness and credential maintenance.
  The Shop and Ads settings cannot substitute for one another; malformed or
  unconfigured direct endpoints fail closed. Runtime allowlisting is still
  mandatory. Legacy configuration expectations and other platforms are unchanged.

Official Ads callback contract:
https://business-api.tiktok.com/gateway/docs/index?doc_id=1738373141733378

This section is an implementation record, not a claim that new code, structures,
credentials, runtime settings or app registrations are already deployed.
