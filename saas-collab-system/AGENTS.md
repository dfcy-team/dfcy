# Creator Module Change Boundary

This branch is reserved for the Creator Management module. Agents must not modify unrelated modules.

## Allowed Paths

- `backend/apps/influencers/**`
- `backend/tests/test_influencer_fulfillment.py`
- `frontend/src/api/influencers.js`
- `frontend/src/views/influencers/**`
- `frontend/tests/ui-p9-influencer-integration.spec.js`
- Creator-module documentation under `docs/` when explicitly requested

## Forbidden Without Explicit User Approval

- Global navigation, menu hierarchy, or application layout
- Global routes and permission catalogs
- Any backend app other than `influencers`
- Any frontend view or API module outside `influencers`
- Deployment, finance, RPA, advertising, commission, or synchronization modules
- Reformatting or refactoring unrelated files

Before every commit, compare the changed-file list against the allowed paths. If any file is outside the allowlist, stop and remove that change from the Creator module commit. Reviewers must treat any unapproved out-of-scope file as a blocking P1 finding.
