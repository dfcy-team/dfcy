# Local RAW mount preparation and paired backup

This is a reviewed-candidate workflow, not an installed production job. Neither
the example Compose file nor the backup command is loaded by release scripts
automatically. New external writes stay disabled until the complete mount and
recovery workflow has been approved and verified on the intended host.

## Mount preparation

Compare `raw-local.prepare.example.yml` with the actual host Compose. It adds a
shared private bind mount for backend and Celery services, with automatic host
directory creation disabled and `RAW_PAYLOAD_STORAGE_ALIAS` explicitly empty.
It does not change service users, images, ports, queues or existing mounts.

Review these deployment values before any application:

- `PRODUCTION_RAW_LOCAL_HOST_ROOT`: an existing, dedicated private directory on
  the intended application filesystem; example `/opt/saas-collab/production/raw-archive`.
- `PRODUCTION_RAW_NAMESPACE`: stable namespace, e.g. `production-raw`.
- Ownership: the runtime UID must access the 0700 directory. Verify all actual
  backend/worker identities; do not silently change their users in this change.
- Disk reserve: default 10 GiB. Space is shared with application/log/backup
  growth; the guard is not a quota and does not reserve concurrent capacity.

The prepared mount path inside containers is `/var/lib/saas/raw-archive`.
Deploying this preparation template alone does not enable local RAW writes.
Actual production mounts and backup scheduling remain separate operations.

## Produce a paired recovery point

Use an already completed database backup. Restore that exact SQL backup into
an isolated database running compatible migrations. Configure an isolated
management-command environment to point at that restored database, with no
production write credentials or provider network access. Never execute the
manifest command against `production-backend`'s live default database.

The `--snapshot-confirmed` flag records an operator assertion; it cannot prove
which SQL file was restored. Preserve the restore execution evidence and use
`verify-database` to compare every external reference from the restored
database, including counts, with the package. A successful file-only `verify`
is not a substitute for this database comparison.

The following commands are examples for that isolated environment. `default`
must refer to the restored snapshot, not production. Source RAW is mounted
read-only and must remain immutable/retained during copying.

```sh
python manage.py raw_local_backup manifest \
  --database default --snapshot-confirmed --output /backup/refs.jsonl

python manage.py raw_local_backup pack \
  --manifest /backup/refs.jsonl --database-backup /input/database.sql.gz \
  --source-root /input/raw --namespace production-raw \
  --output /backup/raw-package

python manage.py raw_local_backup verify \
  --package /backup/raw-package --database-backup /input/database.sql.gz

python manage.py raw_local_backup verify-database \
  --database default --snapshot-confirmed \
  --package /backup/raw-package --database-backup /input/database.sql.gz
```

`pack` creates only a new private directory and never overwrites an existing
package. It streams metadata and files, checks gzip/canonical content hashes,
binds the package to the database backup SHA-256, and writes a completion
receipt after object verification. Missing data, mixed unsupported storage
aliases or mismatched database references fail explicitly. Default output
free-space reserve is 10 GiB; `--min-free-bytes 0` is for tiny isolated tests,
not a recommended production setting.

Retain **both** the original database backup and the complete RAW package.
The package binds but does not embed the potentially large SQL backup. A
failed incomplete output directory is evidence, not a valid recovery point;
the tool does not remove it or any source data automatically.

## Archive transport and restoration

Existing SQL-only backup jobs are insufficient. After `verify` and
`verify-database` succeed, an established `.tgz` transport can accept one
offline bundle:

```sh
python manage.py raw_local_backup archive \
  --package /backup/raw-package --database-backup /input/database.sql.gz \
  --output /backup/recovery-point.tgz
```

The command verifies the package again, then creates a private 0600 `.tgz`
containing only `database.sql.gz` (or `database.sql`) and `raw-package/...`.
It streams content, checks the archived member list, sizes and SHA-256 values,
and rejects source changes and existing output paths. The default free-space
reserve is 10 GiB. It only creates the file: it does not transfer, unpack,
restore, schedule, or enable production storage. This is candidate code and
must be explicitly reviewed and installed in the intended isolated workflow;
it is not wired into a production job. Keep the SQL and package until the
existing transport process has independently verified the transferred file.

Restoration is deliberately not automatic. Restore SQL to an isolated
database and validate the package with `verify-database`. Restore `objects/`
as the local RAW root, preserving directory/file permissions, the `raw_local`
alias and the namespace. Keep new writes disabled while testing reads and
replay. The tool never deletes source files or runs database restore SQL.

Before enabling production writes, rehearse the actual MySQL restore,
snapshot-to-manifest mapping, full package transfer and application readback.
SQLite synthetic tests demonstrate workflow logic, not the production MySQL
backup or scheduled retention chain. Attach backup/transport receipts before
marking the external archive recovery point complete.
