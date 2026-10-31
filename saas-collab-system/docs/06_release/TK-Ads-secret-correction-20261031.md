# TikTok Ads credential correction - 2026-10-31

## Scope and result

- Aliyun production, tenant 1, advertising integration config 33 only.
- Updated user-provided application secret through the existing authenticated
  `rotate_integration_secret_values` endpoint and custody service.
- Configuration version: 4 -> 5. Audit record: 1096188. HTTP 200.
- Custody readback matched the supplied secret. No secret is included here.
- Existing endpoint normalizes `platform_config.redirect_uri` to the validated
  callback. The complete configuration tuple was not byte-for-byte unchanged.
- Verified final callback and nested redirect URI:
  `https://xtsy.dingfengchuangyu.com/integrations/tiktok-ads/direct-callback`.
- Verified final flags: network enabled, read enabled, write disabled;
  API type advertising; config status verified. TK1PH Ads scope check passed.
- No account permission changes, Shop authorization changes, synchronization
  jobs, application code deployment, or service restart in this operation.

## Provider evidence and remaining acceptance

An intentionally invalid, non-user authorization code was used for a bounded
diagnostic request. Before correction, TikTok reported that the app ID did not
exist or the secret was incorrect. With the supplied secret, TikTok instead
reported invalid input data. This is not a successful token exchange and does
not prove advertiser binding. No old user authorization code was replayed.

Next: refresh the original SaaS page, create a fresh Ads manual authorization
session, authorize, and submit its corresponding callback once. Verify token
custody, advertiser discovery and explicit store mapping separately.

## Administrator version synchronization

This is a database/custody configuration change, not a Git code release.
Preserve config 33 version 5 and its custody references during deployment;
do not overwrite with old environment values or seed data. Never copy secrets
into code, release notes or screenshots. Earlier API hotfixes remain documented
in `TK-Ads-config-hotfix-20261030.md` and `TK-Ads-diagnostics-20261031.md`.
