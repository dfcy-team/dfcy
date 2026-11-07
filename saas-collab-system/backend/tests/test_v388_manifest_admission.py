"""Offline V388 admission regression; all temporary evidence is TEST-ONLY."""
import json
from hashlib import sha256
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import scripts.production_build_only as build_only


class V388ManifestAdmissionTests(unittest.TestCase):
    APPROVED_SOURCE = "d477e713c604cbcd9db0c92fbd1d0bf74e5bb38b"
    APPROVED_MIGRATION = "332b96aab71b8bd156e37bbf918c66ceebc7fe9764fd9a1dad9e74b988a4f684"

    def args(self, repo=build_only.REPOSITORY, source=build_only.V388_SOURCE_SHA,
             migration=build_only.V388_MIGRATION_SHA, redis=build_only.REDIS_IMAGE):
        return [repo, source, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
                redis, migration]

    def test_exact_v388_pair_and_legacy_pairs_are_admitted(self):
        self.assertEqual(build_only.V388_SOURCE_SHA, self.APPROVED_SOURCE)
        self.assertEqual(build_only.V388_MIGRATION_SHA, self.APPROVED_MIGRATION)
        # The pre-V388 admission table rejects this new exact pair.
        with patch.object(build_only, "V388_SOURCE_SHA", "0" * 40):
            with self.assertRaises(ValueError):
                build_only.make_manifest(*self.args())
        manifest = build_only.make_manifest(*self.args())
        self.assertEqual(manifest["git_sha"], build_only.V388_SOURCE_SHA)
        from scripts.production_build_only import (
            HISTORICAL_MIGRATION_SHA, HISTORICAL_TARGETS, MIGRATION_SHA,
            V330_SOURCE_SHA, V330_SOURCE_MIGRATION_SHA, V384_CLOUD_IDENTITY,
        )
        legacy = [(build_only.BASELINE_SHA, MIGRATION_SHA)]
        legacy += [(sha, HISTORICAL_MIGRATION_SHA) for sha in HISTORICAL_TARGETS]
        legacy += [(V330_SOURCE_SHA, V330_SOURCE_MIGRATION_SHA),
                   (build_only.V330_CLOUD_SHA, build_only.V330_SOURCE_MIGRATION_SHA),
                   (V384_CLOUD_IDENTITY["source_sha"], V384_CLOUD_IDENTITY["migration_sha256"]),
                   ("d8c28d8cfed9a97f372b5b91074d3b22461110bb",
                    "c0647e94edbdb112acf840fb46376a595f8305233b6f9d099ecd6885279586c0")]
        for source, migration in legacy:
            with self.subTest(source=source):
                self.assertEqual(build_only.make_manifest(*self.args(source=source, migration=migration))["git_sha"], source)

    def test_cross_pairs_and_invalid_evidence_are_rejected(self):
        cases = [self.args(migration=build_only.MIGRATION_SHA),
                 self.args(source=build_only.BASELINE_SHA, migration=build_only.V388_MIGRATION_SHA),
                 self.args(repo="wrong/repo"), self.args(redis="redis:latest"),
                 self.args(source="z" * 40), self.args(migration="g" * 64),
                 self.args(migration="332b96aab71b8bd156e37bbf918c66ceebc7fe9764fd9a1dad9e74b988a4f684x")]
        cases += [self.args(migration=old) for old in
                  (build_only.HISTORICAL_MIGRATION_SHA, build_only.V330_SOURCE_MIGRATION_SHA,
                   build_only.V384_CLOUD_IDENTITY["migration_sha256"])]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    build_only.make_manifest(*args)

    def _evidence(self, directory):
        (directory / "TEST-ONLY.txt").write_text("Synthetic fixture; not official evidence.\n", encoding="utf-8")
        expected = directory / "expected"
        expected.mkdir()
        for name in ("lock-scope", "related-regression", "preflight-rejection", "sync-workspace-regression", "sales-regression"):
            (expected / f"{name}.nodeids").write_text(f"test_only_{name}.py::test_only_case\n", encoding="utf-8")
            root = ET.Element("testsuites")
            suite = ET.SubElement(root, "testsuite", tests="1")
            ET.SubElement(suite, "testcase", classname=f"test_only_{name}", name="test_only_case")
            ET.ElementTree(root).write(directory / f"{name}.xml")
        (directory / "index-migration.json").write_text(json.dumps({
            "status": "pass", "migration": "commerce.0006_salesorder_currency_catalog_idx",
            "index": "idx_sales_order_currency", "columns": ["tenant_id", "currency"],
            "forward_and_reverse_checked": True, "rows_unchanged": True,
            "production_database_used": False, "fresh_migration_chain_validated": False,
            "schema_mode": "synthetic current-model schema",
        }), encoding="utf-8")
        return expected

    def test_actual_manifest_cli_path_writes_success_and_no_receipt_on_rejection(self):
        scenarios = [
            ("approved", {}, None, True),
            ("repository", {"GITHUB_REPOSITORY": "wrong/repo"}, None, False),
            ("source", {"RELEASE_SHA": "f" * 40}, None, False),
            ("legacy-migration", {}, build_only.MIGRATION_SHA, False),
            ("redis", {"REDIS_IMAGE": "redis:latest"}, None, False),
            ("backend-digest", {"BACKEND_DIGEST": "sha256:short"}, None, False),
            ("frontend-digest", {"FRONTEND_DIGEST": "latest"}, None, False),
            ("missing-evidence", {}, "missing", False),
            ("skipped-evidence", {}, "skipped", False),
            ("failed-evidence", {}, "failed", False),
        ]
        for label, overrides, evidence_fault, should_pass in scenarios:
            with self.subTest(scenario=label), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                expected = self._evidence(directory)
                if evidence_fault == "missing":
                    (directory / "sales-regression.xml").unlink()
                elif evidence_fault in ("failed", "skipped"):
                    tree = ET.parse(directory / "lock-scope.xml")
                    ET.SubElement(tree.find(".//testcase"), "failure" if evidence_fault == "failed" else "skipped")
                    tree.write(directory / "lock-scope.xml")
                argv = ["production_build_only.py", "manifest", "--directory", str(directory), "--expected-directory", str(expected)]
                env = {"GITHUB_REPOSITORY": build_only.REPOSITORY, "RELEASE_SHA": self.APPROVED_SOURCE,
                       "BACKEND_DIGEST": "sha256:" + "a" * 64,
                       "FRONTEND_DIGEST": "sha256:" + "b" * 64,
                       "REDIS_IMAGE": build_only.REDIS_IMAGE, "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"}
                env.update(overrides)
                measured_migration = build_only.MIGRATION_SHA if label == "legacy-migration" else self.APPROVED_MIGRATION
                with patch.object(build_only, "migration_digest", return_value=measured_migration), \
                     patch.dict(os.environ, env, clear=False), patch.object(sys, "argv", argv):
                    if should_pass:
                        build_only.main()
                    else:
                        with self.assertRaises((OSError, ValueError)):
                            build_only.main()
                receipt = directory / "build-only-receipt.json"
                manifest = directory / "release-manifest.json"
                self.assertEqual(receipt.exists(), should_pass)
                self.assertEqual(manifest.exists(), should_pass)
                if should_pass:
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
                    self.assertEqual(payload["git_sha"], self.APPROVED_SOURCE)
                    self.assertEqual(payload["migration_sha256"], self.APPROVED_MIGRATION)
                    self.assertEqual(payload["backend_image"], f"ghcr.io/{build_only.REPOSITORY}/saas-collab-backend@sha256:{'a' * 64}")
                    self.assertEqual(payload["frontend_image"], f"ghcr.io/{build_only.REPOSITORY}/saas-collab-frontend@sha256:{'b' * 64}")
                    self.assertEqual(payload["redis_image"], build_only.REDIS_IMAGE)
                    self.assertEqual(receipt_payload["status"], "BUILT_NOT_DEPLOYED")
                    self.assertEqual(receipt_payload["manifest_sha256"], sha256(manifest.read_bytes()).hexdigest())
                    self.assertFalse(receipt_payload["compose_runtime_verified"])
                    self.assertFalse(receipt_payload["vm_mutated"])
                    self.assertFalse(receipt_payload["cloud_mutated"])
                    self.assertFalse(receipt_payload["ledger_mutated"])
                    self.assertFalse(receipt_payload["deployment_authorized_by_this_receipt"])


if __name__ == "__main__":
    unittest.main()
