# Report export storage candidate

## Scope and defaults

Local candidate on V306 (`19b37da7`). Does not modify V313's frozen RAW backup
candidate, enable cloud writes, create a bucket, migrate existing exports, or
delete any source. Reconcile with the latest cumulative release before use.

`storage_alias=''` always means the existing `REPORT_EXPORT_ROOT`. New rows store
the alias, tenant-qualified key, byte size, SHA-256, content type, tenant/owner,
source-scope snapshot and expiry; the file body is never stored in the database.
The nullable metadata migration does not read or rewrite historical file bodies.

## Opt-in deployment configuration (not applied by this candidate)

Set `REPORT_EXPORT_OSS_BUCKET`, `REPORT_EXPORT_OSS_REGION`,
`REPORT_EXPORT_OSS_ENDPOINT` (official HTTPS regional/internal OSS endpoint),
`REPORT_EXPORT_OSS_CREDENTIAL_FILE` (read-only private credentials mount), and
`REPORT_EXPORT_OSS_NAMESPACE` (default `exports`). This only registers
`report_exports_oss`. Enabling new writes separately requires
`REPORT_EXPORT_WRITE_STORAGE_ALIAS=report_exports_oss`.

Backend and celery-background need matching alias/namespace/credential mounts;
keep aliases available for existing object rows when reverting new writes to
local. Keep the original report volume while any old rows reference it. No
deployment compose or secret file has been changed here.

The OSS class reuses V306's private TLS/credential/immutable-write transport, but
overrides its RAW-only key contract. It accepts only report csv/txt objects,
private ACL, AES256 and no-overwrite PUT. Its current 32MiB limit bounds object-store
exports; larger object requests fail clearly. Local writes and legacy reads
retain their existing size behavior. The source export renderer is still
row-capped and materializes bytes as before; this is not an ETL optimization.

## Downloads and failure handling

No public or provider-signed object URL is issued. The existing application
grant binds export, user and tenant; the file endpoint rechecks current download
and source scopes, ownership and expiry before opening storage. Read bytes are
hashed and size-checked into a temporary spool before FileResponse; large spools
roll to local scratch disk. That disk must be private, capacity-monitored and
ephemeral. FileResponse closes the returned spool.

Upload and readback verification must finish before metadata becomes visible.
Provider errors are sanitized and never trigger local fallback. An upload may
be accepted while its response or DB commit fails: it becomes an orphan, not a
valid export. Do not retry uncertain writes or automatically delete the object;
reconcile the independent object inventory with DB IDs under an approved task.

## Expiry, backup and isolated recovery

`REPORT_EXPORT_TTL_SECONDS` remains unchanged (default one day, bounded by the
existing configuration). Expiry rejects download; it is not a deletion policy.
No RAW 30-day policy or bucket lifecycle rule is applied to reports/vouchers.

`python manage.py report_export_storage --tenant-id TENANT` reports counts only.
An explicitly requested `--write-package NEW_DIRECTORY` copies verified active
files and records expired exports as metadata-only; it never reads expired file
bodies, overwrites an existing package, deletes an object, or changes DB rows.
A failed package has no complete manifest. `export_backup.verify_package`
checks all declared body sizes and hashes without following file symlinks.

This report-only package must be paired with the same coordinated MySQL snapshot
containing tenant, owner, permissions, source scopes, grants and file metadata.
It is not the RAW V313 package and cannot be restored by the RAW command. A
manifest hash must be retained outside the package; self-contained hashes detect
corruption but do not authenticate a maliciously rewritten package.

Recovery plan: freeze an export-ID cutoff, capture a coordinated DB snapshot,
write and verify packages, then copy to an independently controlled backup
destination. Restore the DB into an isolated tenant-aware environment; verify
package and external manifest hash, restore only verified active objects to
their original tenant-qualified keys in an isolated namespace/bucket, and map
the storage alias to that isolated destination. Restore old local files into an
isolated root. Never write to the original bucket during recovery. Expired rows
stay expired; backup presence never grants permission. Run ordinary authenticated
grant/download tests with authorized, other-user, other-tenant, revoked and
expired cases. There is deliberately no automatic restore command in this
candidate; its implementation and independent backup transport remain gates.

## Historical migration and release gates

The observed two production records are an inventory fact from the supplied
storage report, not a migration count or proof their files are readable. Under
separate authorization, inventory exact tenant/ID/key/expiry/size/hash, verify
source, copy to an immutable report key, read back, then update one record's
alias/key/size/type transactionally with audit. Keep the source and rollback map.
Missing/expired objects are reported rather than regenerated or silently skipped.

Before enabling: final-base schema and migration check, exact SDK 1.4.1 test on
real private bucket, TLS/internal endpoint/no-redirect validation, Linux ACL and
scratch capacity, least-privilege GET/PUT without RAW/delete access, lifecycle
review, transport of independent backups, isolated recovery, failure injection,
and original-account download/source-scope/expiry tests. Local mocked tests do
not establish any of these live-environment gates.
