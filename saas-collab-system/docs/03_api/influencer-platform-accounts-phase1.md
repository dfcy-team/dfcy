# Influencer Platform Accounts, Phase 1

## Scope

An influencer remains one tenant-owned parent. Manual TikTok, Facebook,
Instagram, and YouTube accounts belong to that parent through
`InfluencerPlatformAccount.influencer_id`. Existing sample, task, blacklist,
and BD attribution relationships continue to reference the parent unchanged.
Contact channels are not platform accounts and are never converted implicitly.
No scraping, cross-platform statistics, or attribution rewrite is included.

## Fields and Identity

Each platform slot has its own handle, external account ID, display name,
homepage URL, nullable follower count, and active status. Unknown followers
are `null`; explicitly entered zero remains zero.

The editor and internal library use `nickname_id` (UI: 昵称 ID) for the
canonical platform username, e.g. `misschedly`, backed by `Influencer.handle`.
`account_nickname` (UI: 账号昵称) is the decorated display name, e.g.
`Miss CHE DIY`, backed by `InfluencerProfile.display_name`. Reads fall back to
legacy `name` only for the account nickname, never for the username. Existing
stored `name` is not rewritten by nickname edits; new aliases-only creates
initialize a bounded compatibility name from the account nickname or username,
retaining the full nickname in its dedicated profile field.
Numeric `external_influencer_id` is unchanged. Missing usernames display as
unconfirmed; a profile URL does not silently infer or backfill identity.

Secondary aliases map to the child `handle` and `display_name`. Supplying
both an alias and its legacy field requires equal normalized values; a
conflict returns 400. Omitted aliases remain unchanged.

The legacy primary identity is retained. The aggregate editor cannot change
its platform, handle, or populated external ID. An empty primary external ID
may be supplied once. Secondary identities are editable with conflict checks.
An inactive secondary slot is reused rather than reassigned or deleted.
No more than one slot per parent and platform is allowed. Active identities
are reserved within the tenant and platform, including legacy parent records.

## API

- `GET /api/internal/influencers/{id}/?include_form=true` returns a complete
  editable aggregate, explicit `profile: null` when absent, active contacts,
  platform account slots, and `updated_at`.
- `POST /api/internal/influencers/?include_form=true` creates one aggregate.
- `PATCH /api/internal/influencers/{id}/?include_form=true` requires
  `If-Match: <updated_at>`. A stale version returns 409 without partial writes.
- Omitted sections stay unchanged. Profile fields are partial updates.
  Contacts are an active-list replacement; `contacts: []` deactivates them.
  Platform accounts are upserted by platform; omitted platforms and an empty
  array stay unchanged. Explicit `is_active: false` deactivates a secondary.
- Form access requires an active internal tenant user, `influencers.manage`,
  and ALL data scope. Ordinary reads remain redacted. Platform filtering
  includes the legacy primary and registered active secondary platforms.
- `GET /api/internal/influencers/?include_nickname_id=true` and the equivalent
  detail purpose expose `nickname_id` and `account_nickname` only to active
  internal tenant users with `influencers.view` and ALL scope. This purpose
  also permits searching primary and active secondary usernames. Default
  reads still omit both `handle` and `nickname_id`.

## VM34 Release

Use the actual VM34 baseline `af245102cc9febd72a06390b5944b4728f165f25`,
preserving its TikTok integrations, environment, custody mounts, and frontend
configuration overlays. Do not replace unrelated modules with main.

1. Verify the current image and idle workers, and retain a database backup.
2. Apply schema-only `0028_influencer_platform_account` and
   `0029_primary_identity_indexes`. They add a table, two nullable derived
   hash fields, and indexes; no business records are deleted or merged.
3. Upgrade backend, celery, and celery-beat together before backfilling.
4. For each tenant, repeatedly run
   `python manage.py backfill_influencer_identity_indexes --tenant <id> --limit 500 --apply`
   until both remaining counts are zero. Without `--apply`, the command is
   read-only. Batches update only derived hashes, preserving original fields,
   foreign keys, and timestamps; replay is a zero-write operation.
5. Compare original business-row counts and hash-only invariants, verify
   runtime API reads, frontend assets, and service health.

New identity claims fail closed while legacy index coverage is incomplete.
All active writers must run the upgraded models: an old writer can otherwise
leave a stale hash. Primary saves, profile saves, and TikTok duplicate-handle
fanout maintain their derived indexes. A rollback can retain additive schema;
do not drop tables or restore over newer business data without approval.

Until their separate maintenance paths are aligned, do not run
`refresh_influencer_video_profiles` concurrently with aggregate writes
(profile-first lock order), or use direct-model/manual primary external-ID
fills (`backfill_influencer_identity_metrics`) once a primary child exists.
Use the aggregate API, which synchronizes the once-only numeric-ID fill.

VM10, Aliyun, and a pull request are outside this first VM34 test deployment.
