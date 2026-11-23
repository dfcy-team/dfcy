"""Regression for same-version append preserving live financial hotfix metadata."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "release_notes.py"
spec = importlib.util.spec_from_file_location("v518_live_history", SCRIPT)
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


class LiveHotfixHistoryTests(unittest.TestCase):
    def test_current_history_pin_is_exact_captured_live_file(self):
        self.assertEqual(notes.V518_HISTORY_SHA,
            "0174464f65c46597576477cad0fce6a6eaad1097861b0b4036fc50f32c3a147f")

    def test_prepare_and_check_preserve_hotfix_fields_and_all_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "saas-collab-system/frontend/src/data/releaseNotes.json"
            target.parent.mkdir(parents=True)
            history = [{"version": "2.44.518", "date": "2026-11-20",
                "changes": ["financial review hotfix", "original change"],
                "hotfixes": [{"batch": "finance-candidate-review-20261123",
                             "date": "2026-11-23", "changes": ["financial review hotfix"]}]}]
            history += [{"version": f"2.44.{version}", "date": "2026-11-19",
                         "changes": [f"history {version}"]} for version in range(517, 460, -1)]
            raw = (json.dumps(history, ensure_ascii=False, indent=2) + "\n").encode()
            history_path = root / "live-history.json"
            history_path.write_bytes(raw)
            target.write_bytes(raw)
            append = ["2026-11-23 cumulative component"]
            expected = [dict(history[0], changes=history[0]["changes"] + append), *history[1:]]
            expected_raw = (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode()
            changes_path = root / "changes.json"
            changes_path.write_text(json.dumps(append), encoding="utf-8")
            binding = {"status": "REVIEWED_SAME_VERSION_RECONCILIATION", "version": "2.44.518",
                "history_sha256": notes._sha(raw), "release_date": "2026-11-23",
                "append_changes": append, "append_changes_sha256": notes._sha(
                    json.dumps(append, ensure_ascii=False, separators=(",", ":")).encode()),
                "candidate_notes_before_sha256": notes._sha(raw), "base_source_sha": notes.V518_BASE_SHA,
                "source_material_sha256": "a" * 64, "expected_notes_sha256": notes._sha(expected_raw)}
            binding_path = root / "binding.json"
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            auth_path = root / "authorization.json"
            auth_path.write_text(json.dumps({"status": "AUTHORIZED", "scope": notes.V518_SCOPE,
                "human_message": "保留并继续", "binding_sha256": notes._sha(binding_path.read_bytes())}), encoding="utf-8")
            args = argparse.Namespace(command="prepare", notes=str(target), history=str(history_path),
                version="2.44.518", date="2026-11-23", changes_file=str(changes_path),
                reconciliation_binding=str(binding_path), reconciliation_authorization=str(auth_path))
            with patch.object(notes, "V518_HISTORY_SHA", notes._sha(raw)), \
                 patch.object(notes, "repo_root", return_value=root), \
                 patch.object(notes, "source_material_sha256", return_value="a" * 64), \
                 patch.object(notes.subprocess, "check_output", return_value="f" * 40), \
                 patch.object(notes.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                notes.prepare(args)
                self.assertEqual(target.read_bytes(), expected_raw)
                notes.check(args)
                actual = json.loads(target.read_bytes())
                self.assertEqual(actual[0]["hotfixes"], history[0]["hotfixes"])
                self.assertEqual(actual[1:], history[1:])
                tampered = json.loads(raw)
                del tampered[0]["hotfixes"]
                history_path.write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "history raw SHA"):
                    notes.check(args)


if __name__ == "__main__":
    unittest.main()
