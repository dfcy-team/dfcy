# V2.44.221 sync startup error candidate (build only)

Baseline: registered V2.44.220 source `87ef1377164a525750a870cb863b28cd03d6d759`. This document is a candidate review record, not a deployed-version declaration.

Application delta is confined to the two existing startup queries and worker preflight error handling. `select_for_update(of=("self",))` retains tenant predicates and joined authorization/configuration reads while locking only the target SyncJob. It preserves same-job serialization and prevents independent jobs from locking shared parent rows.

Only DRF ValidationError raised directly by `validate_manual_sync_job` before execution becomes an explicit `blocked` result. The existing queued-run failure persistence, dispatch blocking and failure alert remain. Authorization/capability/configuration checks are not weakened. The result contains only status, created=false and the fixed SYNC_PREFLIGHT_FAILED code; it does not claim business success or return exception contents. Non-validation preflight errors and execution-stage ValidationError still propagate.

The 9 real-MySQL lock cases, existing 131 related cases and 6 preflight rejection cases are mandatory publication gates with zero failures and zero skips. The separate manual build-only workflow also keeps the existing application checks, SQLite migration consistency/full regression and locked frontend build. No application models, migrations, permission/menu/scope dictionaries, production Compose, Dockerfiles, or existing release workflows change.

The synthetic MySQL gate tests the current model schema, not fresh-install migrations; the unchanged development.0002 view-DDL limitation is retained explicitly. No automatic repair of production authorization, credential bootstrap/replay, platform call, queue mutation or deployment is performed by the build-only workflow. A production rollout requires independent target checks, recoverable backup verification and separate final authorization.
