# P3-ARCH-API-CONTRACT-ALIGN-001 API Contract Alignment Report

## Scope

This report compares `origin/main`, Development A commit `638cfb4`, and Development B commit `2fa2f87`. It freezes documents only and does not modify either development branch or business code.

## Decisions

1. Backend resource naming with existing permission tests is authoritative.
2. Analytics dashboards compose metrics and aggregates rather than adding duplicate overview, sales, or inventory endpoints.
3. Alerts split inventory and business; replenishment uses recommendations; lifecycle history uses decisions; config uses definitions, values, and change-logs.
4. Finance remains under `/api/finance/*` and report exports under `/api/report/*`.
5. All collection responses move to `count`, `next`, `previous`, and `results` inside the standard response envelope.

## Ownership

- Development A: final URL, serializer, response, pagination, errors, tenant/data scope, permissions, and API tests.
- Development B: paths, request parameters, response and pagination parsing, error UI, page mapping, and pending/mock/connected state.

## Safety

The contract preserves finance authorization, tenant/data scope, export audit, and human confirmation boundaries. It contains no real platform access, credentials, real data, automatic purchasing, clearance, lifecycle execution, financial action, or RPA execution.

## Self Check

- One final resource name exists for every frozen capability.
- No frontend-only path is authorized as connected.
- No duplicate compatibility endpoint is requested.
- PR #12 and PR #10 remain Draft until their contract work and R1 review finish.
- This branch modifies documents only.
