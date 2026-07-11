# P2-B-007 platform access risk placeholders change log

## Scope

- Added read-only frontend placeholders for future real platform access risk review.
- Did not implement real platform configuration, OAuth redirect, credential input, or production connection.

## Added pages

- `/settings/platform-risk`
  - File: `frontend/src/views/settings/PlatformAccessRisk.vue`
  - Shows platform access status, sandbox/mock status, production disabled status, risk notes, and forbidden items.
- `/settings/platform-readiness`
  - File: `frontend/src/views/settings/PlatformIntegrationReadiness.vue`
  - Shows security review, credential custody, network isolation, permission audit, rollback, gray release, and high-risk action readiness.
- `/settings/security-review`
  - File: `frontend/src/views/settings/SecurityReviewChecklist.vue`
  - Shows dedicated security review checklist placeholders.

## Mock data

- File: `frontend/src/mock/platformRisk.js`
- Platforms covered:
  - BigSeller
  - Shopee
  - TikTok/TK
  - Bank
  - Payment
- All production statuses default to `production_disabled`.
- High-risk actions default to `false`.

## Boundaries

- No real Token, Cookie, Session, API Key, API Secret, account, password, bank account, or payment credential input.
- No real production connect button.
- No real OAuth redirect.
- No real bank or payment configuration.
- No real BigSeller, Shopee, TikTok/TK, bank, or payment connection.
- No backend changes.
- No `rpa-agent/` changes.
- No `docs/04_rpa/` changes.

## Verification

```bash
cd frontend
npm run build
```

Result:

- Build status: success.
- Main app chunk: `dist/assets/index-BJjbAU0r.js`, about `13.47 kB`, gzip `3.81 kB`.
- New page chunks:
  - `PlatformAccessRisk-rMVme0s5.js`, about `1.30 kB`.
  - `PlatformIntegrationReadiness-C9YGVh9R.js`, about `1.35 kB`.
  - `SecurityReviewChecklist-B3rWafzL.js`, about `1.06 kB`.
- Remaining warning: Element Plus vendor chunk is still larger than `500 kB`, about `923.26 kB`.
- Blocking: no.
