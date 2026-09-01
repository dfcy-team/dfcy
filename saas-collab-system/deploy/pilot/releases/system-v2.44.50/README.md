# V2.44.50 custody sidecar release

This directory contains an architect-controlled, migration-free increment from
the deployed `v2.44.49` baseline. The required candidate SHA is supplied at
deployment time in `candidate-commit.txt`; it must be a full descendant of
`61c68a59323e70dab226b5c6f441bf1bb14a00b3`.

Run on the application VM, in order:

1. Populate the protected `.env.pilot` paths from `env.v24450.example`.
2. Run `bootstrap-custody-v24450.sh` as root. It creates no secret and fixes
   ownership/modes for the non-root sidecar.
3. Run `deploy-v24450.sh` (or `PRECHECK_ONLY=1 deploy-v24450.sh`).
4. After runtime verification passes, run `register-v24450.sh` as the
   architecture/release-control account.
5. Run `post-verify-v24450.sh`; it is read-only and leaves
   `OWNER_VERIFICATION_REQUIRED` pending for the owner.

`rollback-v24450.sh` switches only application containers to the immutable
`v2.44.49` images. It does not delete custody data, restore a database, run
Docker migrations, or publish a host port for the sidecar.

No master key, token, certificate private key, or populated `.env.pilot` may
be copied into Git, a build context, an image layer, or a release log.
