"""Exact identity checks and build manifest for the V382 build-only route."""
import re
import argparse
import json
import os
from pathlib import Path

from scripts.production_build_only import verify_github_release_evidence

REPOSITORY = "dfcy-team/dfcy"
SOURCE_SHA = "1380fd0f0a7016f21e6093a33d1571c2cb4d4853"
SOURCE_TREE = "26f9830bf039764a3be1382b325c7364c83d2ade"
RELEASE_VERSION = "2.44.382"
MIGRATION_SHA = "c0647e94edbdb112acf840fb46376a595f8305233b6f9d099ecd6885279586c0"
REDIS_IMAGE = "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"


def validate_source(release_sha, source_tree, release_version, migration_sha,
                    controller_sha, repository, main_sha, branch_response,
                    checks_response, controller_checks_response):
    expected = (release_sha == SOURCE_SHA and source_tree == SOURCE_TREE
                and release_version == RELEASE_VERSION
                and migration_sha == MIGRATION_SHA and repository == REPOSITORY)
    if not expected:
        raise ValueError("source does not match the frozen V382 identity")
    if not re.fullmatch(r"[0-9a-f]{40}", controller_sha or "") or controller_sha != main_sha:
        raise ValueError("controller must execute from protected main")
    if (not isinstance(branch_response, dict)
            or branch_response.get("commit", {}).get("sha") != main_sha):
        raise ValueError("protected main does not point to the controller SHA")
    verify_github_release_evidence(branch_response, checks_response, SOURCE_SHA)
    verify_github_release_evidence(branch_response, controller_checks_response, controller_sha)
    return True


def make_manifest(repository, release_sha, source_tree, migration_sha,
                  backend_digest, frontend_digest, redis_image):
    validate_identity(repository, release_sha, source_tree, migration_sha)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", backend_digest or ""):
        raise ValueError("invalid backend image digest")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", frontend_digest or ""):
        raise ValueError("invalid frontend image digest")
    if redis_image != REDIS_IMAGE:
        raise ValueError("unapproved Redis image")
    return {
        "schema_version": 1, "environment": "production", "repository": repository,
        "git_sha": release_sha, "release_sha": release_sha,
        "backend_image": f"ghcr.io/{repository}/saas-collab-backend@{backend_digest}",
        "frontend_image": f"ghcr.io/{repository}/saas-collab-frontend@{frontend_digest}",
        "redis_image": redis_image, "migration_sha256": migration_sha,
        "compose_sha256": "owner-controlled-on-target",
    }


def validate_identity(repository, release_sha, source_tree, migration_sha):
    if (repository, release_sha, source_tree, migration_sha) != (
            REPOSITORY, SOURCE_SHA, SOURCE_TREE, MIGRATION_SHA):
        raise ValueError("unapproved V382 source identity")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["manifest"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    manifest = make_manifest(
        os.environ["GITHUB_REPOSITORY"], os.environ["RELEASE_SHA"],
        SOURCE_TREE, MIGRATION_SHA, os.environ["BACKEND_DIGEST"],
        os.environ["FRONTEND_DIGEST"], os.environ["REDIS_IMAGE"],
    )
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    import hashlib
    receipt = {
        "schema_version": 1, "status": "BUILT_NOT_DEPLOYED",
        "release_version": RELEASE_VERSION, "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE, "migration_sha256": MIGRATION_SHA,
        "controller_sha": os.environ["GITHUB_SHA"],
        "workflow_run_id": os.environ["GITHUB_RUN_ID"],
        "workflow_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "manifest_sha256": hashlib.sha256((args.directory / "release-manifest.json").read_bytes()).hexdigest(),
        "build_evidence": {"required_source_checks": "passed-for-exact-source-sha",
                            "required_controller_checks": "passed-for-exact-controller-sha",
                            "quality_and_mysql_gates": "workflow-dependencies-passed",
                            "image_migration_fingerprint": "verified-inside-built-backend-image"},
        "vm_mutated": False, "cloud_mutated": False,
        "deployment_authorized_by_this_receipt": False,
    }
    (args.directory / "build-only-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
