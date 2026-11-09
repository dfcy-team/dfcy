# TikTok Shop renewal follows the global switch

## Scope

- Shop renewal enablement and the credential scanner both follow
  `platforms.tiktok.auto_refresh_enabled`.
- Legacy `auto_refresh_bindings` no longer enables scheduling independently
  or prevents normal saved Shop authorizations from inheriting the switch.
- Exact bindings remain required for the approved callbackless refresh
  exception. Tenant, application, store, actor permission, credential,
  authorization status, concurrent-run and ambiguous-rotation guards remain.
- No Ads renewal changes, credential exports, collection task changes,
  capability activation, or database migrations.
- Enabled means policy enabled, not a successful refresh. Blocked and expired
  states must continue to be shown honestly.

## Verification

68 tests passed in a disposable container using the existing backend image,
with no network, no production credentials, 0.5 CPU and 512 MiB memory.
Suites: `test_tiktok_managed_renewal.py` and
`test_tiktok_global_refresh_switch.py`.
The database-dependent scanner and pilot regression tests were updated but
have not been executed in this change.

## Release boundary

Not deployed by this change. Do not overwrite the current backend hotfixes.
Before deployment, compare the live file to the expected base, save a rollback
copy, and verify the credential worker has no in-flight rotation. Backend API
and credential-worker processes must load the same new policy. Do not restart
normal collection workers. Do not manually refresh all tokens as a smoke test.
Read back per-shop states and scheduler evidence after deployment; an enabled
label alone is not acceptance evidence.

This branch is stacked on the existing collection progress hotfix branch.
Merge that prerequisite first or apply only this change's commit to the chosen
release baseline.
