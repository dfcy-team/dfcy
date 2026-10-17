# Influencer Business Numbers

## Scope

This change submits the previously VM34-tested outreach/sample numbering work.
It does not include TikTok, Ads, proxy, or other API integration changes.
The terminal-task information banner is omitted; completed/cancelled tasks still
permit only task-number corrections. Business fields stay disabled in the UI and
rejected by the service. Removing the banner does not reopen terminal workflows.

## Independent Identifiers

| Field | Meaning | Allocation |
| --- | --- | --- |
| `fulfillment_no` | Sample business number | Shared tenant-level `YPDD` sequence, at least five digits |
| `type_no` | Sample type serial | Independent tenant-level `DRJL`, `YYJL`, etc. sequences, at least four digits |
| `OutreachTask.task_no` | Linked outreach task number | Independent tenant-level `DRJL` task sequence |

Numeric database IDs are not business numbers. The list keeps the sample number
and linked task information; the former task-ID column now shows the type serial.
Task and sample type numbers can use the same text because they belong to separate
namespaces. New numbers use the largest numeric suffix plus one, not record count,
database ID, lexicographic order, or the previous visible row.

## Editing Contract

- Task detail PATCH accepts optional `task_no`, nonblank and at most 80 characters.
- Sample detail PATCH accepts optional `fulfillment_no` and `type_no` under the
  existing manage permission, tenant scope, `If-Match`, and audited transaction.
- Task renames are read through the existing foreign key on every related sample;
  they do not rewrite sample numbers, owners, identities, or attribution.
- Identifier-only sample edits do not ship the sample, refresh confirmed costs,
  replace SKU items, recompute the task, or change the BD attribution snapshot.
- Ordinary fact/item edits retain the existing current-confirmed-cost behavior.
- Before the explicit historical backfill, a missing type serial may remain empty
  during ordinary edits or sample-number-only corrections. Existing type serials
  cannot be cleared. Such edits do not implicitly run the historical backfill.
- Changing a linked sample to `direct` is rejected; existing relationships remain.
- A type change keeps YPDD and allocates a new type serial unless the caller
  explicitly supplies a different serial.
- Current, renamed, and soft-deleted numbers stay reserved. Conflicting identifiers
  return 409; stale edits remain 409. Invalid fields return validation errors.
- Reserved old source numbers can identify the same externally identified record
  on import replay, but cannot overwrite a manual rename or claim another record.
- Creation remains server-numbered for ordinary API callers. Controlled source
  adapters retain their existing explicit historical-number capability.

`InfluencerNumberReservation` is tenant-owned and has no public CRUD endpoint.
Writers acquire the tenant lock before checking/allocating/reserving numbers.
Task/sample owner foreign keys are validated against the same tenant.

## Migration And Historical Backfill

The canonical main-branch migration is
`influencers.0039_sample_business_numbers`, following
`0038_affiliate_business_identity`. It only adds the nullable type field, its
unique constraint, and the reservation table/constraints. It performs no data
backfill and drops no tables or records.

Before backfill, legacy type-prefixed fulfillment numbers matching their row's
link type already occupy that type sequence (including soft-deleted rows).
Allocation and manual type-number corrections must not claim another row's
legacy serial. Ordinary edits remain available without assigning a type number.

The explicit `backfill_sample_business_numbers` command requires an active internal
actor with both outreach/sample management permissions and ALL data scope.

1. Back up the relevant tables and pause conflicting writes for the target tenant.
2. Run the command without `--apply`, with `--tenant-id`, `--actor-id`, and a new
   private `--report-path`. Review the proposed renames, reservations, and counts.
3. Applying requires `--apply --expected-plan <preview> --report-path <new-report>`.
   A changed source digest or an existing/unwritable report aborts the transaction.
4. Preserve existing YPDD numbers. Legacy type-prefixed sample numbers become type
   serials and receive new YPDD numbers; original numbers remain reserved aliases.
   Unknown legacy number shapes abort for review rather than being guessed.
5. Reconcile protected business facts and run another preview. A successful repeat
   proposes zero sample changes and zero new reservations.

The command includes soft-deleted records without restoring them. It changes only
the approved identifiers, optimistic version, and update timestamp. It emits a
batch audit and a detailed private report. Serialization, flush, fsync, and close
must finish before the database transaction commits. Failures roll back all number,
reservation, and audit writes. Reports contain business identifiers and must not
be published with code or copied into PR comments.

## VM34 Overlay Is A Separate Deployment Baseline

VM34 already received the same schema shape using the staging-only
`0040_sample_business_numbers` migration after API-specific migrations absent from
main. This PR intentionally does not import that API migration chain.

Do not overlay this main-branch backend or run its migration blindly against that
already-migrated staging database: the migration names and predecessor graph are
different. A future full-main cutover must compare migration state, actual schema,
constraints, existing aliases, and data receipts, then explicitly approve a
state-mapping plan. Never drop/recreate the reservation table, rerun AddField over
an existing column, or fake-apply migrations without verifying schema equivalence.
Normal main-based environments use the new migration and preview/apply procedure.

The later VM34 banner-removal deployment is frontend-only: it neither migrates nor
repeats the historical backfill. Latest API code and proxies are preserved.

## Regression Coverage

Backend tests cover tenant/permission isolation, aliases including deleted rows,
numeric allocation, source replay, stale writes, audit rollback, identifier-only
cost-refresh rejection, linked task display/search, and durable-report rollback.
Frontend runtime tests cover separate fields, number-only requests, duplicate
draft retention, absent terminal banner, and all terminal business-field locks.
