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
RECONCILIATION_BASE = "23031cd05a99534d04f7c4f9c287f38c4d3975c6"


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


def reconciliation_entry(version, history, history_path, binding_path, authorization_path):
    """Return the only allowed same-version reconciliation, or None."""
    if not binding_path and not authorization_path:
        return None
    if not binding_path or not authorization_path:
        raise ValueError("reconciliation requires both reviewed binding and human authorization")
    binding, authorization = read_json(binding_path), read_json(authorization_path)
    if not isinstance(binding, dict) or binding.get("status") != "REVIEWED_AND_APPROVED":
        raise ValueError("reconciliation binding is not independently reviewed and approved")
    if not isinstance(authorization, dict) or authorization.get("production_cutover_authorized") is not False:
        raise ValueError("invalid human reconciliation authorization")
    if authorization.get("base_source_sha") != binding.get("base_source_sha") or not authorization.get("approved_proposal"):
        raise ValueError("reconciliation binding does not match human authorization")
    if binding.get("version") != version or version != "2.44.384":
        raise ValueError("reconciliation is restricted to version 2.44.384")
    if not re.fullmatch(r"[0-9a-f]{40}", str(binding.get("base_source_sha", ""))):
        raise ValueError("invalid reconciliation base source SHA")
    if binding["base_source_sha"] != RECONCILIATION_BASE:
        raise ValueError("reconciliation base source SHA is not the fixed approved base")
    repo = Path(__file__).resolve().parents[2]
    try:
        subprocess.run(["git", "-C", str(repo), "cat-file", "-e", RECONCILIATION_BASE + "^{commit}"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", RECONCILIATION_BASE, "HEAD"],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("current source is not a Git descendant of the approved base") from exc
    history_bytes = Path(history_path).read_bytes()
    if hashlib.sha256(history_bytes).hexdigest() != binding.get("history_sha256"):
        raise ValueError("reconciliation history bytes do not match approved binding")
    matches = [x for x in history if x["version"] == version]
    if len(matches) != 1:
        raise ValueError("reconciliation history changed or has duplicate target versions")
    additions = binding.get("append_changes")
    append_date = validate_date(binding.get("append_date"))
    if not isinstance(additions, list) or not additions or any(not isinstance(x, str) or not x.strip() for x in additions):
        raise ValueError("binding must contain exact non-empty appended changes")
    original = matches[0]
    if any(not isinstance(original.get(k), list) for k in ("changes",)):
        raise ValueError("target history entry has invalid changes")
    candidate = dict(original)
    candidate["changes"] = [*original["changes"], *additions]
    # The append date is a binding to the cumulative text, not a rewrite of the hotfix date.
    if binding.get("append_date") != append_date:
        raise ValueError("invalid append date")
    return candidate


def prepare(args):
    validate_version(args.version)
    history = read_entries(args.history)
    existing = read_entries(args.notes)
    changes = read_json(args.changes_file)
    if not isinstance(changes, list) or not changes or any(not isinstance(x, str) or not x.strip() for x in changes):
        raise ValueError("changes-file must contain a non-empty JSON array of non-empty strings")
    release_date = validate_date(args.date or datetime.now(SHANGHAI).date().isoformat())
    entry = {"version": args.version, "date": release_date, "changes": changes}
    matches = [item for item in history if item.get("version") == args.version]
    reconciled = reconciliation_entry(args.version, history, args.history, args.reconciliation_binding, args.reconciliation_authorization)
    if reconciled is not None:
        binding = read_json(args.reconciliation_binding)
        if changes != binding["append_changes"] or release_date != binding["append_date"]:
            raise ValueError("prepare inputs do not match approved appended strings and date")
        expected = [reconciled, *[x for x in history if x["version"] != args.version]]
        if existing == expected:
            return
        if existing != history:
            raise ValueError("notes differ from approved reconciliation baseline")
        atomic_write(args.notes, (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
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
    validate_version(args.version)
    notes = read_entries(args.notes)
    history = read_entries(args.history)
    reconciled = reconciliation_entry(args.version, history, args.history, args.reconciliation_binding, args.reconciliation_authorization)
    if not notes or notes[0].get("version") != args.version:
        raise ValueError("latest release notes version does not match requested version")
    if reconciled is not None:
        expected = [reconciled, *[x for x in history if x["version"] != args.version]]
        if notes != expected:
            raise ValueError("notes differ from approved reconciliation; history or appended content changed")
        return
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
