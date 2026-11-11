# Archived production patches

These exact local transformation scripts are archived so the production-only
date-label change is code, not merely a release note. They do not deploy files.
Do not run against a newer production asset or use them to bypass release review.

To reproduce in an isolated directory, put the original backed-up asset there
as sample-live-20261105.js. Its SHA256 must be
a64957eb7b149ffbe8e4c329b217a114d77dd20d8b66f7a3b95098d1d48151e0.
Then run the scripts in order, copying each output to the next input name:

1. patch-sample-layout.cjs: sample-layout-patched.mjs -> sample-layout-public-verify.js
2. shrink-sample-layout.cjs: sample-layout-compact.mjs -> sample-layout-compact-public.js
3. sample-one-sku.cjs: sample-one-sku.mjs -> sample-one-sku-public.js
4. sample-fluid-layout.cjs: sample-fluid-layout.mjs -> sample-fluid-public.js
5. sample-date-labels.cjs: sample-date-labels.mjs is the final asset.

Final SHA256: 129d7efd80477b97a6c251e19d78c7d93ce5d8c36870b6b9c1b34458439ed764.
Production backups, verification limits, and rollback safeguards are documented
in ../SAMPLE-LAYOUT-HOTFIX-20261105.md. Normal release must reconcile the existing
date-filter source, not rebuild an older main and lose that feature.
