# TK Ads API configuration hotfix - 2026-10-30

## Post-approval connection completion

Runtime record 38 (v35) was verified effective after user approval. Existing audited `integration_config_detail` PATCH was invoked as actor 1 for connection 33 with expected version 3. Only callback_url and network_enabled were updated; resulting config version is 4, read remains true and write remains false. Callback is the approved Ads direct callback. No task was enabled and no token was exchanged.

Read-only production verification: connection 33 has ads_oauth_ready=true and no OAuth blockers. For actors 1 and 41, TK1PH store 23 access payload includes advertising option 33; the OAuth permission/readiness scope check passes. This establishes configuration readiness, not completed TikTok authorization or provider API acceptance.

## Approval correction - use v35, not v34

The earlier v34 draft (record 37) accidentally included `modules` from the resolved runtime snapshot. The frontend correctly disables approval for mixed module/runtime documents. This was a preparation error, not evidence of missing administrator permissions.

Replacement v35 (record 38) was created through the existing configuration service, using the stored effective v33 (record 36), not the merged runtime snapshot. Only the Ads callback and OAuth allowlist differ; equality of all other fields was asserted inside the transaction. v35 has no `modules` key and remains pending approval, submitted as actor 1. v34 remains unchanged for audit; do not approve it. Effective configuration is still record 36. No account permissions, authorization credentials, sync tasks or services changed in this correction.

Local setup draft generation now removes `modules`; 9 isolated setup tests passed, including an assertion that the persisted draft excludes module data. This local setup-page code is not deployed; the replacement draft uses the already-deployed configuration service. Another authorized administrator must approve v35 before Ads connection 33 can be finalized.

## Deployment receipt

- Target: Aliyun production, production-backend-1 only.
- Hotfix identifier: TK-ADS-CONFIG-20261030-01.
- Base commit: 435c29841191de7b2dd5351c30389281856d2141.
- This is a direct container hotfix, NOT a new image release or merged PR.
- Server backup and deployed source: /opt/saas-collab/production/hotfix-tk-ads-config-20261030/{before,after}/.
- Gunicorn received HUP for graceful worker reload. Master PID remained 2526105; new workers 2791023 and 2791024.
- No frontend, account, Shop authorization, database schema, token or sync-task changes.

## Exact changes to preserve during image synchronization

1. backend/apps/integrations/serializers.py: only the TikTok advertising API type is exempt from the Shop-only seller.authorization.info requirement. Callback and network approval checks remain enforced.
2. backend/apps/integrations/platform_schema_service.py: validate Marketing public fields independently (api_type, numeric app_id, optional HTTPS redirect_uri). Reject secrets and unknown fields. Shop schema remains unchanged.

Deployed SHA256:

| File | SHA256 |
| --- | --- |
| serializers.py | 831c4eb186fc27aa762797771715521fcb01b364ea1ef2d52c4583da3c147dee |
| platform_schema_service.py | ff569c2be2249f61095618023eeb0e01f45c6856fabbc0747e3b865d2ee75376 |

Before hashes: serializers.py de7a8abc09ba70337f361db397ddc8ce3c65145a521d5373cb825bfef27d1ff9; platform_schema_service.py 6c86ea9dce1c5df6f739346327f59beef5afcf3635735a0dedb53863e79191d7.

Before recreating containers, merge these two narrow changes into the release source, run tests and build an image. A recreation from the current image loses this hotfix. Do not copy this worktree's unrelated pending frontend/setup changes as part of this fix. Preserve existing production influencer/frontend hotfixes separately.

## Verification and remaining gate

- Local isolated tests: test_ads_config_scope_boundary.py and test_tiktok_ads_setup.py: 17 passed.
- Broader Ads direct/OAuth suite not accepted: existing fixtures supply an environment callback while current code requires valid approved runtime configuration; first direct test fails during setup. Full provider flow is NOT verified.
- Production py_compile and Django system check passed. Website returned HTTP 200 after reload.
- Production read-only serializer verification no longer reports Shop scope/schema errors; it now correctly blocks mismatched/unapproved callbacks.
- Effective runtime remains record 36. Draft record 37 (version 34) is pending approval, submitted by actor 1. It ONLY adds Ads direct callback and allowlist entry; other configuration is preserved.
- Another authorized administrator must inspect and approve version 34, NOT old pending versions. Compare against current effective configuration if it changes before approval.
- Then update Ads connection 33 through the existing audited API: callback_url = https://xtsy.dingfengchuangyu.com/integrations/tiktok-ads/direct-callback, and approved network access. Preserve credentials, existing read flag, and disabled write flag. No sync job should be enabled by this preparation.
- Final store authorization and advertiser ownership confirmation still require the user. No real authorization/code exchange was performed in this deployment.

## Rollback

Restore ONLY the two corresponding files from before/ to the container, run py_compile and manage.py check, then gracefully reload Gunicorn. Do not restore whole images/frontend/database or change accounts. Pending draft 37 is not effective and must not be silently approved as part of rollback.
