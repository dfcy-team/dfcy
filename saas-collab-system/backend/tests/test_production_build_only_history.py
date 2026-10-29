"""Exact-source allowlist contract for the isolated historical build path."""
import os
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.production_build_only import (
    GITHUB_ACTIONS_APP_ID, HISTORICAL_MIGRATION_SHA, HISTORICAL_TARGETS, MIGRATION_SHA,
    expected_testcases, make_manifest, verify_github_release_evidence, verify_junit,
    validate_historical_source, migration_digest,
)


@pytest.mark.parametrize("release_sha,tree_sha", HISTORICAL_TARGETS.items())
def test_allows_only_registered_release_and_exact_tree(release_sha, tree_sha):
    assert validate_historical_source(
        release_sha, tree_sha, HISTORICAL_MIGRATION_SHA
    )["tree_sha"] == tree_sha


@pytest.mark.parametrize("release_sha,tree_sha,migration_sha", [
    ("1" * 40, "2" * 40, HISTORICAL_MIGRATION_SHA),
    (next(iter(HISTORICAL_TARGETS)), "2" * 40, HISTORICAL_MIGRATION_SHA),
    (next(iter(HISTORICAL_TARGETS)), HISTORICAL_TARGETS[next(iter(HISTORICAL_TARGETS))], "3" * 64),
])
def test_rejects_unregistered_sha_wrong_tree_or_wrong_migration(release_sha, tree_sha, migration_sha):
    with pytest.raises(ValueError, match="Unapproved historical source"):
        validate_historical_source(release_sha, tree_sha, migration_sha)


def test_historical_manifest_requires_exact_registered_sha_and_migration():
    sha = next(iter(HISTORICAL_TARGETS))
    manifest = make_manifest("dfcy-team/dfcy", sha, "sha256:" + "a" * 64,
                             "sha256:" + "b" * 64,
                             "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
                             HISTORICAL_MIGRATION_SHA)
    assert manifest["migration_sha256"] == HISTORICAL_MIGRATION_SHA
    with pytest.raises(ValueError):
        make_manifest("dfcy-team/dfcy", "1" * 40, "sha256:" + "a" * 64,
                      "sha256:" + "b" * 64,
                      "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
                      HISTORICAL_MIGRATION_SHA)


def test_junit_gate_requires_same_complete_collected_nodeid_set(tmp_path):
    expected = tmp_path / "suite.nodeids"
    expected.write_text("tests/example_test.py::test_one\ntests/example_test.py::TestGroup::test_two\n")
    assert expected_testcases(expected) == {
        ("tests.example_test", "test_one"),
        ("tests.example_test.TestGroup", "test_two"),
    }
    import xml.etree.ElementTree as ET
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    ET.SubElement(suite, "testcase", classname="tests.example_test", name="test_one")
    ET.SubElement(suite, "testcase", classname="tests.example_test.TestGroup", name="test_two")
    report = tmp_path / "suite.xml"
    ET.ElementTree(root).write(report)
    assert verify_junit(report, expected, "fixture") == 2
    ET.SubElement(suite, "testcase", classname="tests.example_test", name="unexpected")
    ET.ElementTree(root).write(report)
    with pytest.raises(ValueError):
        verify_junit(report, expected, "fixture")
    suite.remove(suite.findall("testcase")[-1])
    suite.findall("testcase")[0].append(ET.Element("skipped"))
    ET.ElementTree(root).write(report)
    with pytest.raises(ValueError):
        verify_junit(report, expected, "fixture")


def branch_evidence():
    branch = {
        "name": "main", "protected": True,
        "protection": {"required_status_checks": {
            "checks": [{"app_id": GITHUB_ACTIONS_APP_ID, "context": "Build / tests"}],
            "contexts": ["Build / tests"],
        }},
    }
    checks = {"total_count": 1, "check_runs": [{
        "id": 10, "name": "Build / tests", "app": {"id": GITHUB_ACTIONS_APP_ID},
        "head_sha": "a" * 40, "status": "completed", "conclusion": "success",
    }]}
    return branch, checks


def test_github_validation_accepts_actual_branch_and_check_runs_payloads():
    branch, checks = branch_evidence()
    result = verify_github_release_evidence(branch, checks, "a" * 40)
    assert result == {"protected": True, "required_checks": 1, "release_sha": "a" * 40}


@pytest.mark.parametrize("mutate", [
    lambda b, c: b.update(protected=False),
    lambda b, c: b["protection"].update(required_status_checks=None),
    lambda b, c: b["protection"]["required_status_checks"]["checks"][0].update(app_id=1),
    lambda b, c: c["check_runs"][0]["app"].update(id=1),
    lambda b, c: c["check_runs"][0].update(head_sha="b" * 40),
    lambda b, c: c["check_runs"][0].update(status="in_progress"),
    lambda b, c: c["check_runs"][0].update(conclusion="failure"),
    lambda b, c: c.update(total_count=2),
    lambda b, c: (c["check_runs"].append({**c["check_runs"][0], "id": 11, "conclusion": "failure"}), c.update(total_count=2)),
])
def test_github_validation_rejects_invalid_protection_or_required_check_state(mutate):
    branch, checks = branch_evidence()
    mutate(branch, checks)
    with pytest.raises(ValueError):
        verify_github_release_evidence(branch, checks, "a" * 40)


def test_controller_helper_imports_from_repo_root_and_fingerprints_business_tree():
    repo_root = Path(__file__).resolve().parents[3]
    controller_backend = repo_root / "saas-collab-system" / "backend"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(controller_backend)
    completed = subprocess.run(
        [sys.executable, "-c", (
            "from pathlib import Path; from scripts.production_build_only import migration_digest; "
            "print(migration_digest(Path('saas-collab-system/backend')))"
        )], cwd=repo_root, env=env, check=True, capture_output=True, text=True,
    )
    current_digest = migration_digest(controller_backend)
    assert completed.stdout.strip() == current_digest
    historical_digest = sha256()
    for path in sorted(controller_backend.glob("apps/*/migrations/*.py")):
        relative = path.relative_to(controller_backend).as_posix()
        if relative in {
            "apps/integrations/migrations/0054_daily_ads_shared_raw.py",
            "apps/permissions/migrations/0054_role_permissions_customized.py",
            "apps/listings/migrations/0005_platformproductdetail_platform_image_url.py",
            "apps/reports/migrations/0013_export_storage_metadata.py",
            "apps/products/migrations/0028_legacy_import_spu_group.py",
            "apps/supply_chain/migrations/0031_settlementrevision_payee_allocations_payeeaccount.py",
        }:
            continue
        historical_digest.update(relative.encode())
        historical_digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    assert historical_digest.hexdigest() == HISTORICAL_MIGRATION_SHA
    assert current_digest != HISTORICAL_MIGRATION_SHA
    release_sha, tree_sha = next(iter(HISTORICAL_TARGETS.items()))
    with pytest.raises(ValueError, match="Unapproved historical source"):
        validate_historical_source(release_sha, tree_sha, current_digest)
