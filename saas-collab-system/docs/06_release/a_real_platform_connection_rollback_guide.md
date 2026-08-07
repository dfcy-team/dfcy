# A-REAL-PLATFORM-CONNECTION rollback guide

1. Disable live initiate/network/refresh using the live-network and security approval switches; keep synchronization off.
2. Block approved platform egress and revoke affected custody references/platform authorizations through authorized operators.
3. Deploy the prior fixed artifact; never use an uncommitted checkout.
4. If database rollback is approved and no post-`0013` reauthorization history must be retained, migrate integrations to `0012`. This removes active binding keys; take an approved encrypted backup first and never commit it.
5. Run Django check, migration checks, focused/full tests and credential scans; verify no live routes emit callback queries.

Do not restore revoked credentials, copy raw tokens from logs/database, manually rewrite status to active, or enable any synchronization during rollback. Retain append-only masked audit evidence and require a new OAuth state/reference for recovery.
