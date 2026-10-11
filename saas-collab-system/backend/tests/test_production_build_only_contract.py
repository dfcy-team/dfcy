"""Offline fail-closed contract tests; no registry or database connection."""
from pathlib import Path
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

from scripts.production_build_only import (
    BASELINE_SHA, MIGRATION_SHA, REDIS_IMAGE, REPOSITORY,
    make_manifest, migration_digest, verify_reports, verify_sales_reports,
    verify_sync_workspace_report,
)


def valid_args():
    return [REPOSITORY, BASELINE_SHA, "sha256:" + "a" * 64,
            "sha256:" + "b" * 64, REDIS_IMAGE, MIGRATION_SHA]


def write_suites(directory, counts=(9, 132, 6), skip=False):
    for name, count in zip(("lock-scope", "related-regression", "preflight-rejection"), counts):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests=str(count))
        for index in range(count):
            case = ET.SubElement(suite, "testcase", name=f"synthetic-{index}")
            if skip and index == 0:
                ET.SubElement(case, "skipped")
        ET.ElementTree(root).write(directory / f"{name}.xml")


def write_sales_evidence(directory, count=85, skip=False, **index_overrides):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(count))
    for number in range(count):
        case = ET.SubElement(suite, "testcase", name=f"sales-{number}")
        if skip and number == 0:
            ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(directory / "sales-regression.xml")
    index = {
        "status": "pass", "migration": "commerce.0006_salesorder_currency_catalog_idx",
        "index": "idx_sales_order_currency", "columns": ["tenant_id", "currency"],
        "forward_and_reverse_checked": True, "rows_unchanged": True,
        "production_database_used": False, "fresh_migration_chain_validated": False,
        "schema_mode": "synthetic current-model schema",
    }
    index.update(index_overrides)
    (directory / "index-migration.json").write_text(__import__("json").dumps(index), encoding="utf-8")


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
    (5, "6cea988b041da684449c38b590f30e9252bfd72d10dea7caae027a30f5bd2ea8"),
])
def test_manifest_rejects_unapproved_or_movable_inputs(index, bad):
    args = valid_args()
    args[index] = bad
    with pytest.raises(ValueError):
        make_manifest(*args)


def test_archive_migrations_cannot_reuse_registered_release():
    assert MIGRATION_SHA == "21eadb03414e1baa9fc71a9e5f56126e2a885bac790c476334deb9b36b1f9838"
    root = Path(__file__).resolve().parents[1]
    archive_migrations = {
        "apps/influencers/migrations/0028_influencer_platform_account.py",
        "apps/influencers/migrations/0029_primary_identity_indexes.py",
        "apps/influencers/migrations/0031_influence_archive_associations.py",
        "apps/influencers/migrations/0032_profile_reference_plain_text.py",
    }
    assert all((root / name).is_file() for name in archive_migrations)
    registered_digest = sha256()
    for path in sorted(root.glob("apps/*/migrations/*.py")):
        name = path.relative_to(root).as_posix()
        if name not in archive_migrations:
            registered_digest.update(name.encode())
            registered_digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    assert registered_digest.hexdigest() == MIGRATION_SHA
    current_digest = migration_digest(root)
    assert current_digest != MIGRATION_SHA
    args = valid_args()
    args[-1] = current_digest
    with pytest.raises(ValueError, match="Unapproved"):
        make_manifest(*args)


@pytest.mark.parametrize("line_endings", [(b"\n", b"\n"), (b"\r\n", b"\r\n"), (b"\r\n", b"\n")])
def test_migration_digest_is_checkout_line_ending_independent(tmp_path, line_endings):
    sources = {
        "apps/alpha/migrations/0001_initial.py": b"# alpha\noperations = []\n",
        "apps/zeta/migrations/0001_initial.py": b"# zeta\noperations = []\n",
    }
    expected = sha256()
    for (name, source), ending in zip(sources.items(), line_endings):
        path = tmp_path / name
        path.parent.mkdir(parents=True)
        path.write_bytes(source.replace(b"\n", ending))
        expected.update(name.encode())
        expected.update(source)
    assert migration_digest(tmp_path) == expected.hexdigest()


@pytest.mark.parametrize("change", ["source", "path", "additional_migration"])
def test_migration_digest_still_detects_source_and_migration_set_changes(tmp_path, change):
    path = tmp_path / "apps/alpha/migrations/0001_initial.py"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# alpha\noperations = []\n")
    original = migration_digest(tmp_path)
    if change == "source":
        path.write_bytes(b"# alpha\noperations = ['changed']\n")
    elif change == "path":
        path.rename(path.with_name("0002_initial.py"))
    else:
        path.with_name("0002_next.py").write_bytes(b"operations = []\n")
    assert migration_digest(tmp_path) != original


def test_migration_digest_rejects_missing_source(tmp_path):
    with pytest.raises(ValueError, match="Missing migration source"):
        migration_digest(tmp_path)


def test_advertising_migration_registration_matches_source():
    import json
    from hashlib import sha256

    root = Path(__file__).resolve().parents[1]
    registration = json.loads((root.parent / "docs/06_release/shopee_ads_migration_registration_20261010.json").read_text())
    assert registration["migration_sha256"] == MIGRATION_SHA
    assert [row["name"].split(".")[1][:4] for row in registration["migrations"]] == ["0042", "0043", "0044"]
    for row in registration["migrations"]:
        assert sha256((root / row["path"]).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == row["sha256"]


def test_migration_digest_is_stable_across_source_line_endings(tmp_path):
    path = tmp_path / "apps/example/migrations/0001_initial.py"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"first\nsecond\n")
    expected = migration_digest(tmp_path)
    path.write_bytes(b"first\r\nsecond\r\n")
    assert migration_digest(tmp_path) == expected
    path.write_bytes(b"first\nchanged\n")
    assert migration_digest(tmp_path) != expected


def test_complete_real_mysql_reports(tmp_path):
    write_suites(tmp_path)
    assert verify_reports(tmp_path)["suites"]["lock-scope"]["passed"] == 9


def test_complete_sales_mysql_reports(tmp_path):
    write_sales_evidence(tmp_path)
    result = verify_sales_reports(tmp_path)
    assert result["testcases"] == 85
    assert result["index_migration"]["forward_and_reverse_checked"] is True


def write_sync_workspace_report(directory, count=128, skip=False):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(count))
    for number in range(count):
        case = ET.SubElement(suite, "testcase", name=f"sync-workspace-{number}")
        if skip and number == 0:
            ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(directory / "sync-workspace-regression.xml")


def test_complete_sync_workspace_mysql_report():
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        write_sync_workspace_report(path)
        report = verify_sync_workspace_report(path)
        assert report["testcases"] == 128
        assert report["production_database_used"] is False
        assert "not fresh migration or formal acceptance" in report["limitation"]


@pytest.mark.parametrize("count,skip", [(127, False), (129, False), (128, True)])
def test_sync_workspace_gate_rejects_wrong_count_or_skips(tmp_path, count, skip):
    write_sync_workspace_report(tmp_path, count, skip)
    with pytest.raises(ValueError):
        verify_sync_workspace_report(tmp_path)


def test_sync_workspace_gate_rejects_missing_or_malformed_xml(tmp_path):
    with pytest.raises(ValueError):
        verify_sync_workspace_report(tmp_path)
    (tmp_path / "sync-workspace-regression.xml").write_text("<bad", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_sync_workspace_report(tmp_path)


@pytest.mark.parametrize("count,overrides", [
    (84, {}), (86, {}), (85, {"rows_unchanged": False}),
    (85, {"columns": ["currency", "tenant_id"]}),
    (85, {"forward_and_reverse_checked": False}),
    (85, {"forward_and_reverse_checked": 1}),
    (85, {"rows_unchanged": 1}),
    (85, {"production_database_used": True}),
    (85, {"fresh_migration_chain_validated": True}),
    (85, {"schema_mode": "fresh migration chain"}),
    (85, {"migration": "commerce.0005_old"}),
])
def test_sales_gate_rejects_missing_or_mismatched_evidence(tmp_path, count, overrides):
    write_sales_evidence(tmp_path, count, **overrides)
    with pytest.raises(ValueError):
        verify_sales_reports(tmp_path)


def test_sales_gate_rejects_skipped_tests_or_missing_index_report(tmp_path):
    write_sales_evidence(tmp_path, skip=True)
    with pytest.raises(ValueError):
        verify_sales_reports(tmp_path)
    write_sales_evidence(tmp_path)
    (tmp_path / "index-migration.json").unlink()
    with pytest.raises(ValueError):
        verify_sales_reports(tmp_path)


def test_sales_gate_rejects_malformed_index_report(tmp_path):
    write_sales_evidence(tmp_path)
    (tmp_path / "index-migration.json").write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_sales_reports(tmp_path)


@pytest.mark.parametrize("counts,skip", [((0, 132, 6), False), ((9, 131, 6), False), ((9, 132, 6), True), ((9, 132, 0), False)])
def test_mysql_gate_rejects_missing_or_skipped_cases(tmp_path, counts, skip):
    write_suites(tmp_path, counts, skip)
    with pytest.raises(ValueError):
        verify_reports(tmp_path)


def test_build_only_workflow_cannot_deploy():
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/production-artifacts-build-only.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "needs: [validate, quality, mysql-lock, mysql-sales, mysql-sync-workspace]" in text
    assert "SYNTHETIC_SALES_TEST_ONLY: 'true'" in text
    assert "mysql@sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242" in text
    assert "sales-reports --directory" in text
    assert "sync-workspace-reports --directory" in text
    assert "SYNTHETIC_SYNC_WORKSPACE_ONLY: 'true'" in text
    assert "mysql-sync-workspace-gate-${{ github.run_id }}-${{ github.run_attempt }}" in text
    assert "git merge-base --is-ancestor" in text
    assert "persist-credentials: false" in text
    assert "provenance: mode=max" in text
    assert "sbom: true" in text
    for forbidden in ("secrets.", "environment: Production", "remote-deploy:",
                      "ssh.exe", "production-deploy ", "production-register "):
        assert forbidden not in text
