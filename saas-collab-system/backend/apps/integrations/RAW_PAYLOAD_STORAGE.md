# RAW payload storage

Inline JSON remains the default. To use external payloads, configure
`RAW_PAYLOAD_STORAGE_ALIAS` to the name of a dedicated entry in Django
`STORAGES` and set `RAW_PAYLOAD_STORAGE_NAMESPACE` to a deployment-specific
name. The target must be private, persistent storage; do not use public media
or a temporary local directory. Payloads are gzip-compressed canonical JSON,
namespaced by environment and tenant, and each write uses a random object key.
The database row is created only after the uploaded object reads back exactly.

The private OSS adapter uses the pinned official Python V2 SDK. Real-provider
permissions, latency/failure and restore testing remain incomplete, so
external storage is not ready to enable in production. Archive and webhook
callers may upload and read back objects while
their existing database transactions/lease heartbeat are active; benchmark
the actual backend and configure bounded operation timeouts before enabling.

New and legacy inline rows can be read by the current code. Turning off
external writes is safe after rollout, but rolling application code back to a
version without the external reader is unsafe while external rows exist.
Objects are not automatically deleted, including after an upload succeeds but
verification or row creation fails.

Keep the original `STORAGES` alias mapping and `RAW_PAYLOAD_STORAGE_NAMESPACE`
available when disabling writes; existing references require both. Restore
procedures must restore the database and private objects together and preserve
that namespace. Namespace names are 1–64 ASCII letters/digits/dots/underscores/
hyphens, beginning with a letter or digit. External payloads are limited to
32 MiB before compression; reads also cap compressed and decompressed input.
Oversized input fails explicitly rather than silently omitting its records.
Provider-specific checks must include representative maximum-size pages.

Affiliate page checkpoints continue to be written inline in this phase, while
their reader supports both representations. No old payloads are migrated or
deleted, and existing immutability protections are unchanged.

## OSS configuration (disabled by default)

Configure the following variables in an isolated deployment first. The values
below are placeholders, not working cloud resources:

```text
RAW_OSS_BUCKET=<private-test-bucket>
RAW_OSS_REGION=cn-hangzhou
RAW_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
RAW_OSS_CREDENTIAL_FILE=/run/secrets/raw-oss.json
RAW_PAYLOAD_STORAGE_NAMESPACE=raw-test
RAW_OSS_CONNECT_TIMEOUT=3
RAW_OSS_READ_TIMEOUT=10
RAW_PAYLOAD_STORAGE_ALIAS=
```

Supplying the bucket registers the `raw_oss` Django storage alias without
activating external writes. Only after isolated validation, setting
`RAW_PAYLOAD_STORAGE_ALIAS=raw_oss` enables the path. Default file/media and
static storage backends remain unchanged. Retain the bucket, endpoint,
credential access and namespace configuration when turning writes off.

The credential file is a private regular JSON file containing `access_key_id`,
`access_key_secret` and optionally `security_token`. Never commit its contents.
Mount it read-only; Unix permissions must exclude group/other access. Replace
it atomically for rotation. Credentials are reloaded for each operation;
expired temporary credentials fail rather than falling back to another account.

Use a dedicated private bucket with Block Public Access enabled, and a scoped
RAM principal limited to the relevant `raw/<namespace>/` prefix. Runtime needs
object read/write access only, not bucket administration or deletion. Check
the effective bucket policy, RAM permissions and encryption permissions in
isolation before activation; object ACL alone does not audit all access paths.

Writes request private object ACL, AES256 encryption and forbid-overwrite.
Object names are random UUIDs. OSS documents that forbid-overwrite is not
effective on versioning-enabled or versioning-suspended buckets; this path does
not claim WORM protection. Retain the application immutability and content hash
checks; do not grant other writers broad object replacement permissions.

Connect/read timeouts and a single SDK attempt limit ordinary network waiting;
they are not a hard total wall-clock deadline for an entire streaming transfer.
Do not advertise a maximum task duration until measured with the real backend.
There is no background retry loop, public URL generation or deletion method.
Failed writes/transactions can leave unreferenced objects for later controlled
review; do not enable automatic lifecycle deletion on this prefix.

Official references:
- https://www.alibabacloud.com/help/en/oss/developer-reference/putobject
- https://gosspublic.alicdn.com/sdk-doc/alibabacloud-oss-python-sdk-v2/latest/alibabacloud_oss_v2.html

## Existing-disk alternative (no OSS required)

`PrivateRawLocalStorage` stores the same compressed objects on a private,
persistent filesystem. Configure an existing absolute root directory and keep
external writes off until that directory's mounts and backup are verified:

```text
RAW_LOCAL_ROOT=/var/lib/saas/raw-archive
RAW_LOCAL_MIN_FREE_BYTES=10737418240
RAW_PAYLOAD_STORAGE_NAMESPACE=production-raw
RAW_PAYLOAD_STORAGE_ALIAS=
```

The root path above is an example, not a created or approved production mount.
`RAW_LOCAL_ROOT` registers `raw_local`; it does not turn on external writes.
Only the explicit value `RAW_PAYLOAD_STORAGE_ALIAS=raw_local` enables new local
archives. OSS bucket, identity and credentials are unnecessary for this mode.
Existing OSS aliases can remain registered for historical references.

Use a dedicated directory owned by the runtime account, outside public media
and web server roots. The application, workers and replay tools must see the
same persistent host directory at the configured container path. Container
writable layers, ephemeral folders and an unmounted intended data directory
are unsuitable. Verify the mount identity before starting a worker; this
backend cannot infer which disk an operator intended to mount.
Subdirectories must remain on the root filesystem; device checks reject nested
mounts so the free-space guard measures the same filesystem that receives data.

The default free-space reserve is 10 GiB, checked before writes. It is a guard,
not a storage reservation or capacity guarantee: concurrent processes and
other services can consume free space. Disk-full failures must be investigated;
the adapter never automatically deletes existing objects to make space.

New files are written to a same-directory private temporary file, flushed and
published without replacing an existing key. The filesystem must support the
required hard-link publication; validate this on the real mount before use.
Unix permission and directory durability checks require Linux validation.
Windows testing cannot establish equivalent Unix permission or crash behavior.
The root and its ancestors must be administrator-controlled; do not allow
untrusted users to replace directories or mounts during operation.

Back up the database and the complete RAW root together. Pause new writes or
use a consistent snapshot boundary, then verify that every external reference
in the database backup has a matching object and matching content hash. Restore
the original alias and namespace; the root location may change when restoring.
Do not count the new database-only backup as a complete recovery point.

This phase does not move older inline rows, reclaim InnoDB files, install a
backup scheduler or alter production Compose mounts. Switching off new writes
must retain old local objects and their alias configuration. Sharing the
application disk changes where bytes grow; it does not create new capacity.
