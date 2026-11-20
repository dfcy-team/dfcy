# Influencer hotfix release prerequisites

PR #597 includes the normal Vue source integration for the priority carousel,
the bounded priority API, private feedback image storage and authenticated reads.
It must not depend on copying a container's import map into a fresh image.
`npm run build` runs `hotfixes:check` before building. Removing the integration
or image implementation blocks that build; the focused runtime tests cover
carousel prop changes, previous/next and image submission/read authorization.

Before a formal release, the release owner must:

1. Include #597 and the task detail fix (#601) plus all other still-active
   hotfixes in the approved candidate. Do not build from an older baseline or
   replace the entire online asset directory with an unrelated build.
2. Run `python manage.py check_influencer_hotfix_compatibility` from the candidate
   backend, using the existing controlled read-only production DB access, before
   any migration or container replacement. Missing already-applied migration
   files are a release blocker, not permission to fake or delete migration rows.
   In particular, the deployed feedback migration has production-only ancestors;
   those sources and their graph must be reconciled before a formal release.
3. Compare the approved runtime hotfix inventory against the candidate, preserve
   unrelated frontend/worker patches, and record immutable image digests and a
   rollback target outside this PR. A passing source check is not a complete
   live hotfix inventory audit and does not itself authorize deployment.
4. Run the frontend and backend tests, migration checks and the read-only
   compatibility command. Back up before running additive migrations through
   the approved release process. Never reverse the feedback/image migrations
   during an application-only rollback.
5. Verify in the candidate and after release: one priority task at a time;
   previous/next; open/close/reopen task details after activity updates;
   feedback submission with image preview and removal; authenticated image
   viewing and tenant/author isolation. Do not create real test feedback without
   separate approval. Keep existing collectors running.

The compatibility command is an explicit preflight for the release owner; it
has not been installed into the live controller by this PR. Current hotfixes
must remain in place until this checklist and the release gates are satisfied.
