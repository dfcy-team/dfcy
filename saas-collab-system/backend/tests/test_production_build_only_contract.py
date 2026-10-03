"""Offline fail-closed contract tests; no registry or database connection."""
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts.production_build_only import (
    BASELINE_SHA, MIGRATION_SHA, REDIS_IMAGE, REPOSITORY,
    make_manifest, migration_digest, verify_reports,
)


def valid_args():
    return [REPOSITORY, BASELINE_SHA, "sha256:" + "a" * 64,
            "sha256:" + "b" * 64, REDIS_IMAGE, MIGRATION_SHA]


def write_suites(directory, counts=(9, 131, 6), skip=False):
    for name, count in zip(("lock-scope", "related-regression", "preflight-rejection"), counts):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests=str(count))
        for index in range(count):
            case = ET.SubElement(suite, "testcase", name=f"synthetic-{index}")
            if skip and index == 0:
                ET.SubElement(case, "skipped")
        ET.ElementTree(root).write(directory / f"{name}.xml")


def test_production_manifest_keeps_existing_contract():
    manifest = make_manifest(*valid_args())
    assert manifest["schema_version"] == 1
    assert manifest["git_sha"] == BASELINE_SHA
    assert manifest["release_sha"] == manifest["git_sha"]
    assert manifest["backend_image"].endswith("@sha256:" + "a" * 64)
    assert manifest["compose_sha256"] == "owner-controlled-on-target"


@pytest.mark.parametrize("index,bad", [
    (0, "another/repository"), (1, "main"), (1, "A" * 40),
    (2, "sha256:short"), (3, "latest"), (4, "redis:latest"), (5, "c" * 64),
])
def test_manifest_rejects_unapproved_or_movable_inputs(index, bad):
    args = valid_args()
    args[index] = bad
    with pytest.raises(ValueError):
        make_manifest(*args)


def test_migration_tree_matches_approved_v220():
    assert migration_digest(Path(__file__).resolve().parents[1]) == MIGRATION_SHA


def test_complete_real_mysql_reports(tmp_path):
    write_suites(tmp_path)
    assert verify_reports(tmp_path)["suites"]["lock-scope"]["passed"] == 9


@pytest.mark.parametrize("counts,skip", [((0, 131, 6), False), ((9, 130, 6), False), ((9, 131, 6), True), ((9, 131, 0), False)])
def test_mysql_gate_rejects_missing_or_skipped_cases(tmp_path, counts, skip):
    write_suites(tmp_path, counts, skip)
    with pytest.raises(ValueError):
        verify_reports(tmp_path)


def test_build_only_workflow_cannot_deploy():
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/production-artifacts-build-only.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "needs: [validate, quality, mysql-lock]" in text
    assert "git merge-base --is-ancestor" in text
    assert "persist-credentials: false" in text
    assert "provenance: mode=max" in text
    assert "sbom: true" in text
    for forbidden in ("secrets.", "environment: Production", "remote-deploy:",
                      "ssh.exe", "production-deploy ", "production-register "):
        assert forbidden not in text
