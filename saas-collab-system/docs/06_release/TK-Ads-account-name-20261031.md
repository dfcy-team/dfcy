# TK Ads capability account names - 2026-10-31

- Production hotfix scope: Ads capability response and its account display only.
- API adds `advertiser_name` from current verified bound OAuth evidence using
  existing tenant/store/config/token/fingerprint checks. No provider call on page load.
- UI shows capability label, account name (or unavailable label), then advertiser ID.
- Source files: backend/apps/integrations/ads_capability_api.py and
  frontend/src/components/TikTokAdsCapabilityMatrix.vue.
- No database migration, credential changes, read-toggle changes or sync jobs.

## Verification

- Isolated unit test passed: correct candidate selected; unverified evidence yields empty name.
- Production Django check passed. Backend workers gracefully reloaded.
- Production readback: Nova.ph store / 7365788829120397328 and
  YX-菲律宾-本土1号店 / 7651940663654678546. Both reads remain enabled, no jobs.
- Generated capability JavaScript passed `node --check`.
- Browser visual verification was not performed; user should refresh the page.

## Deployment and preservation

Backup, generated assets, guarded deployment script and receipt are under
`/opt/saas-collab/production/hotfix-tk-ads-name-20261031/`.

The existing live frontend was preserved. Only the capability render expression
was transformed; new content-addressed chunk and entry files were created and
index.html updated. No whole frontend build or unrelated pending work was deployed.

New entry: index-84691451bdf8.js.
New chunk: IntegrationCapabilityMatrix-d65290e37542.js.
Backend SHA256: 0a54f5c37657de19c07d57c3dbf49e876c18e9a3b0f0965553052f26a5c5e2e0.

This is a direct container hotfix, not an image release. Merge both source changes
into the release before recreating containers, preserving all prior hotfixes.
Rollback only these changes: restore before/ads_capability_api.py to backend and
before/index.html to frontend, then gracefully reload backend workers. Retain old
assets. Do not roll back database configuration or credentials.
