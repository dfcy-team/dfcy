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

SHANGHAI = timezone(timedelta(hours=8))
VERSION_RE = re.compile(r"\d+\.\d+\.\d+\Z")


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
    p.set_defaults(run=prepare)
    p = commands.add_parser("check", help="verify prepared notes and unchanged deployed history")
    p.add_argument("--notes", required=True)
    p.add_argument("--history", required=True)
    p.add_argument("--version", required=True)
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
