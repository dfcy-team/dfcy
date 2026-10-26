# TikTok Shop manual direct import

## Why

The legacy DFCY Shop tool accepts an operator-selected local shop and a callback
without provider-returned state. SaaS previously rejected first binding when both
returned state and an existing trusted platform shop ID were absent. Operators
therefore could not use an otherwise valid seller callback to discover a shop.

This change implements explicit manual credential import, not an automatic OAuth
callback downgrade. It uses the existing SaaS direct provider and custody backend;
the DFCY relay server is not used. Shop IDs and raw tokens must not be copied from
the legacy configuration files into the SaaS business database.

## Flow and boundaries

1. Select the SaaS shop and ready integration configuration; prepare the manual
   flow in the same browser tab. This creates a short-lived signed browser context.
2. Complete seller authorization and paste its fresh, unused, same-SaaS HTTPS
   callback URL. The URL need not contain state or a platform shop ID.
3. Explicitly acknowledge that this is the operator's own authorization, not a
   callback supplied by another person. The UI sends `manual_import_confirmed`
   only for a missing-state manual submission. Automatic callbacks never set it.
4. Validate actor, tenant, permissions, browser verifier, expiry, unchanged config,
   App Key, and region. A supplied wrong/empty state is NOT ignored.
5. Consume the session once, audit `MANUAL_IMPORT_REQUESTED`, exchange the code
   through the existing provider, and query actual authorized shops.
6. First binding remains pending until the operator selects and confirms a
   returned shop. No usable authorization or store ID is installed before this.
   Existing-shop renewal retains exact platform-shop-ID matching.

No migrations, scheduler changes, approval changes, Ads changes, or live data
backfills are included. Uncertain exchanges are not replayed. Existing cleanup,
duplicate identity checks, encrypted custody, and binding confirmation are kept.

## Residual risk

Without returned state, this is an intentional operator import rather than proof
that the platform callback belongs to the initiating OAuth round trip. Browser
context and confirmation do not cryptographically prove callback origin. A
privileged operator who imports someone else's code and confirms the wrong shop
can still misbind it. Use only personally obtained callbacks and verify the
returned shop identity. The normal state-bearing flow remains preferred.

## Release scope

Base: `96dd97a2bd3ea51ef57ae6e1e40741e078122753`, matching the inspected Aliyun
backend and frontend revision. Deployment must retain rollback images and change
only backend/frontend, with no database schema or scheduled worker modification.
Synthetic test success is not proof of a real seller authorization; a fresh code
and operator confirmation are required for live acceptance.
