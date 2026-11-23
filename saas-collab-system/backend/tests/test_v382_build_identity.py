import json
import os
import subprocess
import sys
import pytest

from scripts.v382_build_identity import (
    MIGRATION_SHA, REDIS_IMAGE, RELEASE_VERSION, REPOSITORY, SOURCE_SHA,
    SOURCE_TREE, make_manifest, validate_identity, validate_source,
)
from scripts.production_build_only import GITHUB_ACTIONS_APP_ID


def test_exact_identity_accepts_frozen_v382():
    assert validate_identity(REPOSITORY, SOURCE_SHA, SOURCE_TREE, MIGRATION_SHA) is None


@pytest.mark.parametrize("field,value", [
    ("release_sha", "0" * 40), ("source_tree", "0" * 40),
    ("migration_sha", "0" * 64), ("repository", "attacker/repo"),
])
def test_identity_rejects_mutated_fields(field, value):
    identity = dict(repository=REPOSITORY, release_sha=SOURCE_SHA,
                    source_tree=SOURCE_TREE, migration_sha=MIGRATION_SHA)
    identity[field] = value
    with pytest.raises(ValueError):
        validate_identity(**identity)


def test_identity_rejects_wrong_release_version():
    with pytest.raises(ValueError):
        validate_source(SOURCE_SHA, SOURCE_TREE, "2.44.381", MIGRATION_SHA,
                        "a" * 40, REPOSITORY, "a" * 40, {}, {}, {})


@pytest.mark.parametrize("controller,main", [("b" * 40, "a" * 40), ("", "a" * 40)])
def test_identity_rejects_unprotected_controller(controller, main):
    with pytest.raises(ValueError):
        validate_source(SOURCE_SHA, SOURCE_TREE, RELEASE_VERSION, MIGRATION_SHA,
                        controller, REPOSITORY, main, {}, {}, {})


def evidence(sha=SOURCE_SHA, conclusion="success"):
    branch = {"protected": True, "commit": {"sha": "a" * 40},
              "protection": {"required_status_checks": {
                  "checks": [{"app_id": GITHUB_ACTIONS_APP_ID, "context": "Build / tests"}],
                  "contexts": []}}}
    checks = {"total_count": 1, "check_runs": [{
        "id": 1, "name": "Build / tests", "app": {"id": GITHUB_ACTIONS_APP_ID},
        "head_sha": sha, "status": "completed", "conclusion": conclusion,
    }]}
    return branch, checks


def test_validate_source_requires_source_and_controller_exact_sha_checks():
    branch, checks = evidence()
    main_checks = evidence("a" * 40)[1]
    assert validate_source(SOURCE_SHA, SOURCE_TREE, RELEASE_VERSION, MIGRATION_SHA,
        "a" * 40, REPOSITORY, "a" * 40, branch, checks, main_checks)


@pytest.mark.parametrize("source_sha,source_conclusion,controller_sha", [
    ("b" * 40, "success", "a" * 40),
    (SOURCE_SHA, "failure", "a" * 40),
    (SOURCE_SHA, "success", "b" * 40),
])
def test_validate_source_rejects_wrong_or_failed_checks(source_sha, source_conclusion, controller_sha):
    branch, source_checks = evidence(source_sha, source_conclusion)
    controller_checks = evidence("a" * 40)[1]
    with pytest.raises(ValueError):
        validate_source(SOURCE_SHA, SOURCE_TREE, RELEASE_VERSION, MIGRATION_SHA,
            controller_sha, REPOSITORY, "a" * 40, branch, source_checks, controller_checks)


@pytest.mark.parametrize("backend,frontend,redis", [
    ("sha256:" + "g" * 64, "sha256:" + "b" * 64, REDIS_IMAGE),
    ("sha256:" + "a" * 64, "invalid", REDIS_IMAGE),
    ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "redis:latest"),
])
def test_manifest_rejects_untrusted_image_identity(backend, frontend, redis):
    with pytest.raises(ValueError):
        make_manifest(REPOSITORY, SOURCE_SHA, SOURCE_TREE, MIGRATION_SHA,
                      backend, frontend, redis)


def test_workflow_enforces_frozen_tree_and_source_identity():
    # CI's shallow checkout need not contain the archived business commit.
    # The build workflow fetches that commit and checks its actual Git tree.
    repo = __import__("pathlib").Path(__file__).resolve().parents[3]
    workflow = (repo / ".github/workflows/v382-artifacts-build-only.yml").read_text()
    assert f"""[[ "$REQUESTED_SHA" == '{SOURCE_SHA}' ]]""" in workflow
    assert f"""[[ "$SOURCE_TREE" == '{SOURCE_TREE}' ]]""" in workflow
    assert 'git rev-parse "$REQUESTED_SHA^{tree}"' in workflow
    assert 'git merge-base --is-ancestor "$REQUESTED_SHA" origin/main' in workflow


def test_cli_writes_manifest_and_receipt(tmp_path):
    repo = __import__("pathlib").Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(repo / "saas-collab-system/backend"),
        "GITHUB_REPOSITORY": REPOSITORY, "RELEASE_SHA": SOURCE_SHA,
        "BACKEND_DIGEST": "sha256:" + "a" * 64,
        "FRONTEND_DIGEST": "sha256:" + "b" * 64, "REDIS_IMAGE": REDIS_IMAGE,
        "GITHUB_SHA": "c" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"})
    script = repo / "saas-collab-system/backend/scripts/v382_build_identity.py"
    subprocess.run([sys.executable, str(script), "manifest", "--directory", str(tmp_path)],
                   cwd=repo, env=env, check=True, capture_output=True, text=True)
    manifest = json.loads((tmp_path / "release-manifest.json").read_text())
    receipt = json.loads((tmp_path / "build-only-receipt.json").read_text())
    assert manifest["release_sha"] == SOURCE_SHA
    assert receipt["source_tree"] == SOURCE_TREE
    assert receipt["controller_sha"] == "c" * 40
