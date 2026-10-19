# TikTok Shop read-only mock on VM34

This is a rehearsal of the SaaS integration job pipeline, **not** a live TikTok Shop connection.

## Scope

- A `mock` platform config named `tiktok-shop-readonly-demo-20260929` and one manual `mock_record` job are created in the selected superuser's tenant.
- The mock adapter emits four deterministic fake records: product, order, return, and settlement. The raw mock response and run counters are archived.
- No TikTok API, token file, OAuth callback, marketplace authorization, or external network call is used.
- No product, order, refund, inventory, or finance business fact is written. The run reports four fetched and four skipped records.
- A second execution with the same idempotency key returns the original run rather than duplicating it.

## Usage

Preview without writes:

```bash
python manage.py simulate_tiktok_shop_readonly --username yxj
```

Create and execute once:

```bash
python manage.py simulate_tiktok_shop_readonly --username yxj --apply
```

Only an active, tenant-bound superuser is accepted. The command refuses to reuse a config with network/sync flags or a job bound to a real store/warehouse authorization. In the UI, look under API data access for the mock config, sync job, and run. It is intentionally labeled `mock`, not `tiktok` production.

## VM34 deployment boundary

The VM34 trial image is derived from its **currently running backend image** and overlays only the mock adapter and this command. No frontend, Celery, Celery Beat, or database schema is changed. Roll back the backend image by running its existing compose files without the trial override and recreating only `backend`. Existing mock run records are retained for audit; rollback does not delete data.

Before a real Shop connection, establish independent SaaS OAuth authorization and validate store identity, scopes, read-only contract approval, historical coverage, cursor behavior, and reconciliation with the TK project's source data. This mock run proves none of those production conditions.
