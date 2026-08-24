#!/usr/bin/env python3
"""Static safety gate for the V2.44.41 developer-B data release.

This validator is intentionally runnable without Django, MySQL, Docker, or
the staging dump.  It checks Python syntax, migration guardrails, and the
staging loader's no-reset/no-FK-disable contract.  It does not connect to a
database and does not write application data.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MIGRATE = ROOT / "migrate-devb-influencers.py"
VERIFY = ROOT / "verify-devb-influencers.py"
PREPARE = ROOT / "prepare-staging-devb-influencers.sh"


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION_FAILED: {message}")


def check_python(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        fail(f"Python syntax error in {path.name}: {exc}")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail(f"py_compile failed for {path.name}: {result.stderr.strip()}")


def check_stream_cursor_contract() -> None:
    """Exercise both DictCursor and tuple-row normalization without a DB."""

    spec = importlib.util.spec_from_file_location("devb_migration_contract", MIGRATE)
    if spec is None or spec.loader is None:
        fail("unable to load migration module for stream-row contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    normalizer = getattr(module, "_row_to_dict", None)
    if normalizer is None:
        fail("migration is missing _row_to_dict stream cursor normalizer")
    if normalizer({"id": 7, "code": "x"}, ["id", "code"]) != {"id": 7, "code": "x"}:
        fail("DictCursor row normalization contract failed")
    if normalizer((7, "x"), ["id", "code"]) != {"id": 7, "code": "x"}:
        fail("tuple cursor row normalization contract failed")
    suspect = getattr(module, "is_suspect_text", None)
    if suspect is None or not suspect("\ufffd") or not suspect("????"):
        fail("display-name mojibake detection contract failed")
    if suspect("正常商品名称"):
        fail("display-name mojibake detector rejected valid CJK text")
    reporter = module.Reporter(False, None)
    reporter.issue("contract:name_mojibake")
    if reporter.issues["contract:name_mojibake"]["count"] != 1:
        fail("report issue counter contract failed")
    chooser = getattr(module, "choose_display_name", None)
    if chooser is None or chooser("????", [("title", "目标商品")], reporter, "t", "name") != "目标商品":
        fail("target display-name fallback contract failed")
    if chooser("????", [], reporter, "t", "name") != "":
        fail("unresolved mojibake display-name contract failed")


def check_migration() -> None:
    source = MIGRATE.read_text(encoding="utf-8")
    # These are deliberately checked as SQL tokens rather than broad words,
    # so explanatory documentation can still mention the prohibited actions.
    forbidden = (
        r"\bDROP\s+(?:DATABASE|TABLE)\b",
        r"\bTRUNCATE\s+TABLE\b",
        r"\bDELETE\s+FROM\b",
        r"\bREPLACE\s+INTO\b",
        r"\bSET\s+(?:GLOBAL\s+)?FOREIGN_KEY_CHECKS\b",
    )
    for pattern in forbidden:
        if re.search(pattern, source, re.IGNORECASE):
            fail(f"migration contains forbidden write/reset token: {pattern}")
    required = (
        "--apply",
        "--confirm-tenant-code",
        "--stage-db-host",
        "--stage-db-port",
        "--stage-db-user",
        "--stage-db-password",
        "--target-db-host",
        "--target-db-port",
        "--target-db-user",
        "--target-db-password",
        "effective_db_credentials",
        "STAGE_DB_HOST",
        "TARGET_DB_HOST",
        "tenants_tenant",
        "masterdata_storemaster",
        "masterdata_platformmaster",
        "platform_id",
        "--platform-map-file",
        "source_platform_code",
        "target_platform_code",
        "products_productspu",
        "products_productsku",
        "legacy_sku_code",
        "listings_platformproductdetail",
        "internal_sku_id",
        "choose_display_name",
        "product_name",
        "variant_name",
        "is_suspect_text",
        "ON DUPLICATE KEY UPDATE id = id",
        "source_tenant_id",
        "target_tenant_id",
    )
    for token in required:
        if token not in source:
            fail(f"migration missing safety/mapping token: {token}")
    if "INSERT INTO" not in source:
        fail("migration has no incremental insert path")
    # The target column lists must not copy source primary keys.  A simple
    # source-level assertion catches accidental reintroduction of id columns.
    for match in re.finditer(r"self\._insert\(\s*[\"']([^\"']+)[\"']", source):
        block = source[match.start() : source.find(")\n", match.start())]
        if re.search(r"[\"']id[\"']", block):
            fail(f"target insert for {match.group(1)} includes primary key id")


def check_verify_credentials() -> None:
    source = VERIFY.read_text(encoding="utf-8")
    required = (
        "--stage-db",
        "--stage-db-host",
        "--stage-db-port",
        "--stage-db-user",
        "--stage-db-password",
        "--target-db-host",
        "--target-db-port",
        "--target-db-user",
        "--target-db-password",
        "effective_db_credentials",
        "stage_conn",
    )
    for token in required:
        if token not in source:
            fail(f"verifier missing role-specific credential support: {token}")


def check_prepare() -> None:
    source = PREPARE.read_text(encoding="utf-8")
    required = (
        "CREATE DATABASE IF NOT EXISTS",
        "CREATE TABLE $stage_db.$table LIKE $target_db.$table",
        "gzip -dc",
        "FOREIGN_KEY_CHECKS/d",
        "ALTER TABLE) \\x60",
        "default-character-set=utf8mb4",
        "STAGING_PREPARATION=PASS",
    )
    for token in required:
        if token not in source:
            fail(f"staging preparation missing guardrail: {token}")
    if re.search(r"\b(?:DROP|TRUNCATE)\b", source, re.IGNORECASE):
        fail("staging preparation must not reset/drop databases or tables")
    if re.search(r"SET\s+(?:GLOBAL\s+)?FOREIGN_KEY_CHECKS", source, re.IGNORECASE):
        fail("staging preparation must not disable foreign-key checks")
    if "INSERT INTO" not in source:
        fail("staging preparation does not show qualified INSERT rewrite")


def check_shell_syntax() -> None:
    # Git Bash is present on some deployment hosts but not all developer
    # machines.  When available, use it; otherwise the textual checks above
    # remain deterministic and the release report records the omission.
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ]
    bash = next(
        (
            item
            for item in candidates
            if item
            and Path(item).exists()
            and ("Git" in str(item) or "git" in str(item) or "system32" not in str(item).lower())
        ),
        None,
    )
    if not bash:
        print("shell_syntax=SKIPPED (bash unavailable)")
        return
    result = subprocess.run([bash, "-n", str(PREPARE)], capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or b"").decode("utf-8", "replace").strip()
        fail(f"prepare script shell syntax failed: {detail}")
    print("shell_syntax=PASS")


def main() -> int:
    for path in (MIGRATE, VERIFY):
        if not path.is_file():
            fail(f"missing release file: {path.name}")
        check_python(path)
    check_stream_cursor_contract()
    check_migration()
    check_verify_credentials()
    check_prepare()
    check_shell_syntax()
    print("python_syntax=PASS")
    print("migration_safety=PASS")
    print("staging_guardrails=PASS")
    print("RELEASE_STATIC_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
