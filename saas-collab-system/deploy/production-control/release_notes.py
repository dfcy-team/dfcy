"""Prepare, check, and locally record release notes without touching deployment systems."""
import argparse
from datetime import date, datetime
from datetime import timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import subprocess

SHANGHAI = timezone(timedelta(hours=8))
VERSION_RE = re.compile(r"\d+\.\d+\.\d+\Z")
# Current deployed 58-entry history includes the Nov23 financial review hotfix.
# Its exact bytes were captured before reconciliation; preserve its hotfix metadata.
V518_HISTORY_SHA = "0174464f65c46597576477cad0fce6a6eaad1097861b0b4036fc50f32c3a147f"
V518_BASE_SHA = "9728c548cce4c21d9cbc99aea7407298b4056fc7"
V518_VERSION = "2.44.518"
V518_SCOPE = "V518_SAME_VERSION_NOTES_APPEND"


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def read_entries(path):
    value = read_json(path)
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise ValueError(f"{path}: expected a JSON array of release entries")
    versions = set()
    for entry in value:
        version = entry.get("version")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise ValueError(f"{path}: each entry needs a numeric major.minor.patch version")
        if version in versions:
            raise ValueError(f"{path}: duplicate release version {version}")
        versions.add(version)
        validate_date(entry.get("date"))
        changes = entry.get("changes")
        if not isinstance(changes, list) or not changes or any(not isinstance(x, str) or not x.strip() for x in changes):
            raise ValueError(f"{path}: each entry needs non-empty string changes")
    return value


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
            temp_name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def validate_version(version):
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version must use numeric major.minor.patch format")


def validate_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("date must be a valid YYYY-MM-DD date")
    if parsed.isoformat() != value:
        raise ValueError("date must be a valid YYYY-MM-DD date")
    return value


def validate_monotonic_release(version, release_date, history):
    if not history:
        return
    latest_version = max(tuple(map(int, item["version"].split("."))) for item in history)
    if tuple(map(int, version.split("."))) <= latest_version:
        raise ValueError("new version must be greater than every deployed history version")
    latest_date = max(item["date"] for item in history)
    if release_date < latest_date:
        raise ValueError("new release date cannot be older than deployed history")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def repo_root():
    return Path(subprocess.check_output(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"], text=True, encoding="utf-8").strip()).resolve()


def assert_source_path(path, root):
    path = Path(os.path.abspath(path))
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("source material escapes the candidate repository")
    cursor = path
    while cursor != root:
        if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
            raise ValueError("symlink or junction forbidden in source material")
        cursor = cursor.parent


def source_material_sha256(repo, notes):
    repo, notes = Path(repo).resolve(), Path(notes).resolve()
    paths = subprocess.check_output(["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).split(b"\0")
    records = []
    for raw in sorted(x for x in paths if x):
        rel = raw.decode("utf-8")
        path = repo / rel
        assert_source_path(path, repo)
        expected_notes = repo / "saas-collab-system/frontend/src/data/releaseNotes.json"
        if path == expected_notes:
            continue
        if not path.exists():  # deleted tracked paths are omitted
            continue
        if not path.is_file():
            raise ValueError(f"unsupported non-file source material: {rel}")
        body = path.read_bytes()
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            is_text = False
        else:
            is_text = b"\0" not in body
        if is_text:
            body = body.replace(b"\r\n", b"\n")
        records.append(rel.encode("utf-8") + b"\0" + _sha(body).encode("ascii") + b"\n")
    return _sha(b"".join(records))


def reconciliation(args, require_result=False):
    binding_path, auth_path = getattr(args, "reconciliation_binding", None), getattr(args, "reconciliation_authorization", None)
    if bool(binding_path) != bool(auth_path):
        raise ValueError("reconciliation binding and authorization must be supplied together")
    if not binding_path:
        return None
    binding_raw, auth_raw = Path(binding_path).read_bytes(), Path(auth_path).read_bytes()
    binding, auth = json.loads(binding_raw), json.loads(auth_raw)
    if not isinstance(binding, dict) or not isinstance(auth, dict):
        raise ValueError("binding and authorization must be JSON objects")
    if binding.get("status") != "REVIEWED_SAME_VERSION_RECONCILIATION" or binding.get("version") != V518_VERSION:
        raise ValueError("binding is not an explicitly reviewed V518 same-version reconciliation")
    if auth.get("status") != "AUTHORIZED" or auth.get("scope") != V518_SCOPE or not isinstance(auth.get("human_message"), str) or not auth["human_message"].strip():
        raise ValueError("explicit human authorization with non-empty message is required")
    if auth.get("binding_sha256") != _sha(binding_raw):
        raise ValueError("authorization does not bind the exact binding file bytes")
    history_raw = Path(args.history).read_bytes()
    if _sha(history_raw) != V518_HISTORY_SHA or _sha(history_raw) != binding.get("history_sha256"):
        raise ValueError("V518 reconciliation requires the fixed 58-entry history raw SHA-256")
    history = read_entries(args.history)
    if len(history) != 58 or history[0].get("version") != V518_VERSION:
        raise ValueError("V518 history identity mismatch")
    release_date = validate_date(binding.get("release_date"))
    append = binding.get("append_changes")
    append_raw = json.dumps(append, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not isinstance(append, list) or not append or any(not isinstance(item, str) or not item.strip() for item in append):
        raise ValueError("approved append must contain non-empty strings")
    if binding.get("append_changes_sha256") != _sha(append_raw):
        raise ValueError("approved append changes hash mismatch")
    candidate_before_sha = binding.get("candidate_notes_before_sha256")
    if not isinstance(candidate_before_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", candidate_before_sha):
        raise ValueError("reviewed candidate-before SHA-256 is required")
    notes_path = Path(os.path.abspath(args.notes))
    root = repo_root()
    expected_notes = root / "saas-collab-system/frontend/src/data/releaseNotes.json"
    if notes_path != expected_notes:
        raise ValueError("reconciliation notes path is not the controller's candidate notes file")
    assert_source_path(notes_path, root)
    before_sha = _sha(notes_path.read_bytes())
    if not require_result and before_sha not in {candidate_before_sha, V518_HISTORY_SHA, binding.get("expected_notes_sha256")}:
        raise ValueError("candidate notes do not match the reviewed pre-append bytes")
    base = binding.get("base_source_sha")
    if base != V518_BASE_SHA:
        raise ValueError("binding base_source_sha must equal the reviewed V518 base")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", base, head], stdout=subprocess.DEVNULL).returncode:
        raise ValueError("binding base source is not an ancestor of candidate HEAD")
    if source_material_sha256(root, notes_path) != binding.get("source_material_sha256"):
        raise ValueError("tracked/untracked source material differs from reviewed binding")
    supplied_date = getattr(args, "date", None)
    date_mismatch = supplied_date is not None and validate_date(supplied_date) != release_date
    is_prepare = getattr(args, "command", None) == "prepare" or hasattr(args, "changes_file")
    if is_prepare and validate_date(supplied_date or datetime.now(SHANGHAI).date().isoformat()) != release_date:
        date_mismatch = True
    if args.version != V518_VERSION or date_mismatch:
        raise ValueError("version/date differs from reviewed binding")
    if hasattr(args, "changes_file") and read_json(args.changes_file) != append:
        raise ValueError("changes-file must exactly equal the approved append")
    expected = [dict(history[0], changes=history[0]["changes"] + append), *history[1:]]
    expected_raw = (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if _sha(expected_raw) != binding.get("expected_notes_sha256"):
        raise ValueError("expected notes bytes do not match reviewed binding")
    if require_result and notes_path.read_bytes() != expected_raw:
        raise ValueError("notes bytes differ from the exactly authorized reconciliation result")
    return {"date": release_date, "append": append, "expected": expected_raw, "history": history, "history_sha": _sha(history_raw), "candidate_before_sha": binding.get("candidate_notes_before_sha256"), "notes_path": notes_path}


def prepare(args):
    validate_version(args.version)
    history = read_entries(args.history)
    gate = reconciliation(args)
    notes_path = gate["notes_path"] if gate else Path(args.notes)
    existing = read_entries(notes_path)
    changes = read_json(args.changes_file)
    if not isinstance(changes, list) or not changes or any(not isinstance(x, str) or not x.strip() for x in changes):
        raise ValueError("changes-file must contain a non-empty JSON array of non-empty strings")
    release_date = validate_date(args.date or datetime.now(SHANGHAI).date().isoformat())
    entry = {"version": args.version, "date": release_date, "changes": changes}
    matches = [item for item in history if item.get("version") == args.version]
    if gate:
        if existing == json.loads(gate["expected"].decode("utf-8")):
            return
        current_sha = _sha(notes_path.read_bytes())
        if current_sha not in {gate["history_sha"], gate["candidate_before_sha"]}:
            raise ValueError("candidate notes must be bound VM notes, original history, or exact approved result")
        atomic_write(notes_path, gate["expected"])
        return
    if matches:
        if len(matches) == 1 and matches[0] == entry:
            return
        raise ValueError("version already exists in history with conflicting release notes")
    validate_monotonic_release(args.version, release_date, history)
    if existing == [entry, *history]:
        return
    if existing != history:
        raise ValueError("notes do not match deployed history; refusing to overwrite local changes")
    atomic_write(args.notes, (json.dumps([entry, *history], ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def check(args):
    gate = reconciliation(args, require_result=True)
    if gate:
        return
    validate_version(args.version)
    notes = read_entries(args.notes)
    history = read_entries(args.history)
    if not notes or notes[0].get("version") != args.version:
        raise ValueError("latest release notes version does not match requested version")
    validate_monotonic_release(notes[0]["version"], notes[0]["date"], history)
    if notes[1:] != history:
        raise ValueError("deployed history changed or is not preserved exactly")


def finalize(args):
    validate_version(args.version)
    notes_bytes = Path(args.notes).read_bytes()
    notes = json.loads(notes_bytes.decode("utf-8"))
    if not isinstance(notes, list) or not notes or notes[0].get("version") != args.version:
        raise ValueError("latest release notes version does not match requested version")
    read_entries(args.notes)
    expected = {"status": "PASS", "version": args.version,
                "release_notes_sha256": hashlib.sha256(notes_bytes).hexdigest()}
    receipt = read_json(args.receipt)
    if receipt != expected:
        raise ValueError("receipt must exactly match PASS, version, and release notes SHA-256")
    record = (json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    output = Path(args.output)
    if output.exists():
        if output.read_bytes() == record:
            return
        raise ValueError("success record already exists with different content")
    atomic_write(output, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="prepend a release entry while preserving deployed history")
    p.add_argument("--notes", required=True)
    p.add_argument("--history", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--changes-file", required=True, help="JSON string array")
    p.add_argument("--date")
    p.add_argument("--reconciliation-binding")
    p.add_argument("--reconciliation-authorization")
    p.set_defaults(run=prepare)
    p = commands.add_parser("check", help="verify prepared notes and unchanged deployed history")
    p.add_argument("--notes", required=True)
    p.add_argument("--history", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--reconciliation-binding")
    p.add_argument("--reconciliation-authorization")
    p.set_defaults(run=check)
    p = commands.add_parser("finalize", help="record a matching successful local receipt")
    p.add_argument("--notes", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(run=finalize)
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
