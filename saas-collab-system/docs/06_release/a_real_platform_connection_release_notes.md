# A-REAL-PLATFORM-CONNECTION release notes

Status: Draft / not deployable / not production approved.

This change adds fail-closed live-provider boundaries, approved HTTP or operator-owned local-file custody references, bounded verified-TLS networking, current Shopee/TikTok Shop authorization contracts, callback context protection and immediate query-free result redirects, reauthorization-safe identity constraints, refresh/revoke failure handling, Nginx/Gunicorn callback query suppression, migration `integrations.0013`, and automated tests.

It does not add order, inventory, product, finance, webhook, scheduled, backfill, RPA or platform-write capabilities. Both platform capabilities remain `pending/mock`.

Release is blocked until one remote Review SHA and immutable artifact pass MySQL 8.4, Sandbox, CI, credential scans and approved real pilots. `connected` and Production enablement are not part of this release.
