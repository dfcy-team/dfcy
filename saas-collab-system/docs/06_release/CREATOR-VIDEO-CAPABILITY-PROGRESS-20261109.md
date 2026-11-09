# Creator/video capability progress

## Delivered

The existing store capability matrix now returns and displays an independent
read-only collection_progress section for TikTok stores visible through the
existing authorization scope. No connection-capability enum, database migration,
permission grant, enabled switch, task or timer is created.

Creator counts are current snapshot rows grouped by the queried store, not a
complete creator roster and not proof of creator ownership by that store. Matched
identity counts are separate. Video evidence is the 14 most recently updated
store batches; only completed batches expose their video_count as committed
evidence. No percentage or overall historical completion is invented.

The existing integrations.view permission is additionally required to query
execution evidence. Tenant and store are always passed into both queries.
Store authorization visibility still gates the parent endpoint.

## Explicit limits

- Stores absent from the existing authorization selector are not added here.
- Systemd scheduler state, job logs before batch creation, full failure causes,
  provider scope validity and full historical coverage are not in these models.
  The UI explicitly states scheduler state is unverified.
- No raw error payloads, creator identities, credentials or cursor values are
  returned by this projection.
- A stored running status is not a liveness assertion.
- This patch does not activate paused timers or perform collection.

## Verification

Four isolated query-contract tests cover non-TikTok exclusion, access restriction,
tenant/store filters, identity-count distinction and failed-batch count handling.
They mock the ORM and do not replace database/API integration testing.
## Hotfix deployment receipt

Deployed November 9, 2026 on the v2.44.395 baseline at explicit user request.
No new release number was assigned. PR #542 contains the source and scoped
asset/deployment tooling, not any night-scheduler repair.

The live integrations/views.py matched the baseline SHA256
bcfdfa3d1c7e3ffb1d296e604f7864e0a7579abbd15a9b6339e50627c61280cd.
The hotfix changes that file and adds collection_progress.py. Gunicorn received
a graceful HUP; no Celery container or scheduler was restarted.

Only IntegrationCapabilityMatrix-F6iz7urt.js was replaced on the frontend.
The scoped builder verified all 60 dependency references/implementations and
the shared root export contract before mapping the page to live assets. Existing
index.html, other pages, CSS and release history were not overwritten.

Server backups and receipt are under
/opt/saas-collab/production/operations/collection-progress-20261109/.
Page SHA256 after deployment:
9e9878049cbdad6f250504fdd2c50b15d36362acc24eacdf7a165b8774c6d460.

Follow-up: the first hotfix missed the changed SFC scope ID. The page was using
live CSS with a different scope selector, causing layout regression. The builder
now compares the entire compiled stylesheet after scope substitution, then binds
the page to the verified live scope. Applied a CAS-guarded single-file correction;
the previous page is retained as page-before-scope-fix.js in the backup directory.

Verification: public asset HTTP200 with the new section; authenticated tenant1
matrix view returned HTTP200 with CREATOR and VIDEO progress using real read-only
records. Browser visual acceptance remains pending. This runtime hotfix must be
included in the next formal image release to survive container replacement.
