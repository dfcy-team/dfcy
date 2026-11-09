# Sample multi-product editor: Aliyun hotfix

- Feature commit: `f4148ab2`, PR #505.
- Aliyun image source: `2f0593f8c8f5cb493899a1fe66f45063bdb5af98`.
- Changed only the sample editor JS/CSS, its entry references, and the influencer service/view files. No migrations or business data backfill.
- Independent samples support one sample order with distinct product IDs on SKU rows. Linked outreach samples retain the task product restriction. The existing per-sample SKU uniqueness rule and historical BD attribution are unchanged.

## Reproduce

1. Snapshot the live HTML, main entry, sample component, and the influencer service/view files into `sample-multiproduct-live.json` (base64 values keyed by `index.html`, asset paths, `services.py`, and `views.py`).
2. In an isolated `sample-multiproduct-release` worktree at the image revision, run `npm ci` and a non-mock frontend build to `dist`. Apply only the feature commit's frontend sample editor and backend service/view diffs. Keep the first-SKU country inheritance when reconciling the editor hunk, not the reverted display/save fallback. Build to `dist-multiproduct`.
3. Run `deploy/build_sample_multiproduct_20261109.py <staging-dir>`. It compares the rebuilt baseline with the running component and checks the new component's named import contract. Run the JS syntax check before applying.
4. Pipe the guarded package to `deploy/apply_sample_multiproduct_20261109.py` on the correct host. It refuses unexpected container IDs or current file hashes, retains rollback copies, and rolls back modified entry/backend files on failure.

## Production Receipt

`/opt/saas-collab/production/hotfix-sample-multiproduct-20261109/receipt.json`

The new route uses `SampleFulfillmentList-multiproduct-b93ed19df8c5.js` and `SampleFulfillmentList-multiproduct-3abf5112c646.css`. A permanent release should build the feature from source rather than replay this one-time hotfix. To roll back this deployment, verify current hashes match the receipt, then restore backups 4 (entry), 0 and 1 (backend), gracefully reload Gunicorn and check health. No historical records or costs need to be reverted.
