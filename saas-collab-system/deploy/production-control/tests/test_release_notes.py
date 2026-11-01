import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "release_notes.py"


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = self.root / "history.json"
        self.notes = self.root / "notes.json"
        self.changes = self.root / "changes.json"
        self.output = self.root / "success.json"
        self.entries = [{"version": "1.2.3", "date": "2026-10-30", "changes": ["old"]}]
        self.history.write_text(json.dumps(self.entries), encoding="utf-8")
        self.notes.write_bytes(self.history.read_bytes())
        self.changes.write_text('["new change"]', encoding="utf-8")

    def invoke(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def prep(self, version="1.2.4", date="2026-11-01", success=True):
        return self.invoke("prepare", "--notes", self.notes, "--history", self.history,
                           "--version", version, "--changes-file", self.changes, "--date", date,
                           success=success)

    def test_valid_prepare_preserves_deployed_history_and_check(self):
        self.prep()
        prepared = self.notes.read_bytes()
        self.prep()
        self.assertEqual(self.notes.read_bytes(), prepared)
        notes = json.loads(self.notes.read_text(encoding="utf-8"))
        self.assertEqual(notes[0], {"version": "1.2.4", "date": "2026-11-01", "changes": ["new change"]})
        self.assertEqual(notes[1:], self.entries)
        self.assertEqual(self.history.read_bytes(), json.dumps(self.entries).encode())
        self.invoke("check", "--notes", self.notes, "--history", self.history, "--version", "1.2.4")

    def test_lost_or_changed_history_is_rejected_without_overwrite(self):
        original = self.notes.read_bytes()
        self.notes.write_text("[]", encoding="utf-8")
        bad = self.notes.read_bytes()
        self.prep(success=False)
        self.assertEqual(self.notes.read_bytes(), bad)
        self.assertEqual(self.history.read_bytes(), json.dumps(self.entries).encode())
        self.notes.write_bytes(original)
        self.prep()
        altered = self.root / "altered.json"
        altered.write_text("[]", encoding="utf-8")
        self.invoke("check", "--notes", self.notes, "--history", altered, "--version", "1.2.4", success=False)

    def test_conflicting_version_and_invalid_fields_reject_without_overwrite(self):
        self.entries.insert(0, {"version": "1.2.4", "date": "2026-10-31", "changes": ["different"]})
        self.history.write_text(json.dumps(self.entries), encoding="utf-8")
        self.notes.write_bytes(self.history.read_bytes())
        original = self.notes.read_bytes()
        self.prep(success=False)
        self.assertEqual(self.notes.read_bytes(), original)
        self.notes.write_bytes(json.dumps([self.entries[1]]).encode())
        self.history.write_bytes(json.dumps([self.entries[1]]).encode())
        original = self.notes.read_bytes()
        for version, date_value in (("bad", "2026-11-01"), ("1.2.5", "2026-02-30")):
            self.prep(version, date_value, success=False)
            self.assertEqual(self.notes.read_bytes(), original)
        self.changes.write_text("[]", encoding="utf-8")
        self.prep("1.2.5", "2026-11-01", success=False)
        self.assertEqual(self.notes.read_bytes(), original)
        self.changes.write_text('["new change"]', encoding="utf-8")
        self.prep("1.2.2", "2026-11-01", success=False)
        self.prep("1.2.5", "2026-10-29", success=False)
        self.assertEqual(self.notes.read_bytes(), original)

    def test_prepared_downgrade_and_backdate_reject_without_writes(self):
        cases = (
            {"version": "1.2.2", "date": "2026-11-01", "changes": ["new change"]},
            {"version": "1.2.4", "date": "2026-10-29", "changes": ["new change"]},
        )
        history_bytes = self.history.read_bytes()
        for entry in cases:
            with self.subTest(entry=entry):
                self.notes.write_text(json.dumps([entry, *self.entries]), encoding="utf-8")
                prepared_bytes = self.notes.read_bytes()
                self.prep(entry["version"], entry["date"], success=False)
                self.assertEqual(self.notes.read_bytes(), prepared_bytes)
                self.invoke("check", "--notes", self.notes, "--history", self.history,
                            "--version", entry["version"], success=False)
                self.assertEqual(self.notes.read_bytes(), prepared_bytes)
                self.assertEqual(self.history.read_bytes(), history_bytes)

    def test_check_and_finalize_reject_malformed_entries(self):
        malformed = [{"version": "1.2.4", "date": "not-a-date", "changes": ["change"]}]
        self.notes.write_text(json.dumps(malformed), encoding="utf-8")
        self.invoke("check", "--notes", self.notes, "--history", self.history,
                    "--version", "1.2.4", success=False)
        digest = hashlib.sha256(self.notes.read_bytes()).hexdigest()
        receipt = self.root / "receipt.json"
        receipt.write_text(json.dumps({"status": "PASS", "version": "1.2.4",
                                       "release_notes_sha256": digest}), encoding="utf-8")
        self.invoke("finalize", "--notes", self.notes, "--version", "1.2.4",
                    "--receipt", receipt, "--output", self.output, success=False)
        self.assertFalse(self.output.exists())

    def test_finalize_rejects_bad_receipts_and_is_idempotent(self):
        self.prep()
        digest = hashlib.sha256(self.notes.read_bytes()).hexdigest()
        receipt = self.root / "receipt.json"

        def finalize(value, success):
            receipt.write_text(json.dumps(value), encoding="utf-8")
            before = self.output.read_bytes() if self.output.exists() else None
            self.invoke("finalize", "--notes", self.notes, "--version", "1.2.4",
                        "--receipt", receipt, "--output", self.output, success=success)
            return before

        finalize({"status": "FAIL", "version": "1.2.4", "release_notes_sha256": digest}, False)
        self.assertFalse(self.output.exists())
        finalize({"status": "PASS", "version": "1.2.4", "release_notes_sha256": "0" * 64}, False)
        self.assertFalse(self.output.exists())
        value = {"status": "PASS", "version": "1.2.4", "release_notes_sha256": digest}
        finalize(value, True)
        stored = self.output.read_bytes()
        finalize(value, True)
        self.assertEqual(self.output.read_bytes(), stored)
        finalize({**value, "version": "1.2.5"}, False)
        self.assertEqual(self.output.read_bytes(), stored)


if __name__ == "__main__":
    unittest.main()
