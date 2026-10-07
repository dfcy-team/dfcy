---
name: report-read-performance
description: Inspect and optimize existing Vue 3/Django DRF pages and reports backed by MySQL 8, preserving tenant scopes, pagination contracts and metric definitions. Use for page data fetching, query plans, serialization, aggregate caches and exports in this project.
---

# Existing page and report reads

This repository uses Vue 3, Vite, Axios, Pinia and Element Plus; the backend uses Django 5.2, DRF and mysqlclient. Production profiles require MySQL. Compose's `mysql:8` is a moving tag: obtain `SELECT VERSION(), @@version_comment` from the authorized test connection before interpreting a plan. Historical cloud evidence recorded 8.4.11; do not treat it as a fresh live probe. SQLite can verify local semantics but cannot substantiate MySQL timings or index selection.

Work in an isolated checkout of the accepted baseline. Follow the inner project README's file-location convention. Existing master data, sync and reports may be changing in other chats: record baseline SHA and own only the selected files. Do not copy unrelated dirty workspaces.

When the target is the current Aliyun production system, obtain its live release SHA, runtime revision and effective module switches through an authorized read-only connection. Use that SHA as the candidate baseline and exclude disabled modules from optimization. Classify scope from the frontend module/permission route, not the backend app's name: platform product details can remain active under masterdata while global_listing is disabled. Recheck release drift before final rollout approval.

## Trace and measure

Map `frontend/src/router/index.js` (including aliases/dynamic parameters), shared components and `src/api/*` to `backend/config/urls.py`, app URL modules, views, services and model tables. Record existing list/search/filter/order/page/summary/chart/export paths, static/Mock surfaces and server capabilities separately. A route audit is not a runtime pass.

Start with bounded synthetic rows, API result hashes/bytes, request/query counts and query capture (`CaptureQueriesContext`). Profile permission resolution and serializer access as part of the endpoint. Use small and larger page sizes to expose N+1. Keep exact order, count, null/decimal/time semantics and page boundaries; a query reduction alone is insufficient.

Optimize proven waste: reuse a queryset's evaluated count where appropriate, select/prefetch the relationships actually serialized, move independent front-end reads into bounded parallel execution, cancel/discard stale reads, and retain database filtering/ordering/pagination. Do not turn a documented paged or unpaged contract into a different response. Never cache a GET that records audit or creates an export.

## Tenant and report invariants

Apply tenant and current data scopes before grouping, counting, slicing, caching or reading labels. Report cache keys must contain tenant, actor, current permission/data-scope fingerprint, complete effective query, metric/mapping version and row limit. Revalidate scoped SKU identity before a cache hit; use existing expiration/invalidation contracts. Permission and role changes must not reuse old authorized results. Avoid global response caching in `api/request.js`.

Retain metric definitions, quality filters, lineage and export access checks. Existing `apps/reports/datasets.py` already groups in SQL, bounds groups, caches with permission fingerprints and resolves only returned IDs. Existing inventory workbenches already use server pagination and cached summaries. Assess these before introducing new caches, materialized summaries or background exports; freshness/consistency must justify each addition.

## MySQL evidence

Capture parameterized ORM SQL in the synthetic test DB and use `EXPLAIN FORMAT=JSON`. For an authorized read-only SELECT use `EXPLAIN ANALYZE` when supported, noting it executes the query. Match composite indexes to actual tenant/equality/range/order predicates, observe selectivity and redundant indexes, and test both sparse and dense tenant data. Do not add guessed indexes or force an index from a tiny fixture's plan. Explicit page navigation retains offset semantics; keyset paging requires a compatible product contract.

Sources: [MySQL 8.4 EXPLAIN](https://dev.mysql.com/doc/refman/8.4/en/explain.html), [multiple-column indexes](https://dev.mysql.com/doc/refman/8.4/en/multiple-column-indexes.html), [ORDER BY](https://dev.mysql.com/doc/refman/8.4/en/order-by-optimization.html), [LIMIT](https://dev.mysql.com/doc/refman/8.4/en/limit-optimization.html), [Django 5.2 database optimization](https://docs.djangoproject.com/en/5.2/topics/db/optimization/). MariaDB `ANALYZE FORMAT=JSON`, PostgreSQL `CONCURRENTLY`, partial indexes and database-native cross-engine hashes are not interchangeable with MySQL syntax.

## Acceptance and handoff

Verify equivalent returned values, order/page boundaries, empty results, cross-tenant and restricted-scope behavior. Run targeted tests first, Django checks/migration drift, required frontend permission checks/build for frontend edits, and the relevant broader suite once. Use the project's Vue testing stack; React hooks/RSC guidance does not apply. Validate rendered interactions for front-end changes through the frontend-testing-debugging skill.

Deliver coverage, exact diff, synthetic baseline/after evidence, database version, required checks, unmeasured live P95/scans/bytes and release/rollback instructions. Keep raw logs local and return summaries only. Production migrations and deployments require a reviewable candidate followed by the user's final authorization; local synthetic reversible work can proceed.
