#!/usr/bin/env python3
"""Incrementally merge the developer-B influencer snapshot into tenant 1.

This script is intentionally fail-closed:

* default mode is read-only dry-run;
* source rows are read from a separately prepared staging database;
* target primary keys are never copied;
* every foreign key is resolved by a tenant-scoped natural key or an explicit
  mapping file;
* writes are batched and committed independently;
* no delete/truncate/foreign-key disabling operation is present.

The source dump contains only influencers_* tables.  It does not contain
accounts, stores, platforms, SPUs, or SKUs.  Therefore user/store/SPU
mappings must be supplied explicitly (or the safe store-code derivation can be
enabled).  An unresolved required relation skips that business row and is
reported; it is never guessed.

Typical invocation (inside the backend container or a host with mysqlclient):

  python migrate-devb-influencers.py \
    --stage-db saas_collab_influencers_stage_20260824 \
    --target-db saas_collab_pilot \
    --tenant-code tenant1 \
    --user-map-file /secure/devb-user-map.csv \
    --store-map-file /secure/devb-store-map.csv \
    --spu-map-file /secure/devb-spu-map.csv \
    --report /secure/devb-v24441-dry-run.json

Add --apply only after the dry-run report is reviewed.  For the stated
super-admin source data, a mapping file is still preferred.  The convenience
flags --source-admin-ids and --target-admin-username map only explicitly
listed source account IDs to the target username; no source ID is copied.

The stage and target connections may use different credentials.  Role-specific
CLI options (or STAGE_DB_*/TARGET_DB_* environment variables) take precedence
over the backwards-compatible generic DB_* options.  Database identifiers are
used exactly as provided, including case.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping as MappingABC
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SOURCE_TABLES = (
    "influencers_influencer",
    "influencers_influencerprofile",
    "influencers_influencercontact",
    "influencers_influencerrestriction",
    "influencers_influencerrestrictevent",
    "influencers_storeproductlisting",
    "influencers_skupricesnapshot",
    "influencers_importbatch",
    "influencers_outreachtask",
    "influencers_outreachtarget",
    "influencers_samplefulfillment",
    "influencers_sampleitem",
    "influencers_fulfillmentstatusevent",
)

DERIVED_OR_EMPTY_TABLES = (
    "influencers_bdsampleattributionsnapshot",
    "influencers_bdorderattributionsnapshot",
    "influencers_bdvideoattribution",
    "influencers_bdvideoattributioncurrent",
    "influencers_affiliateimportstate",
    "influencers_affiliateordersnapshot",
    "influencers_affiliateorderrevision",
    "influencers_exchangerate",
    "influencers_tiktokshopvideo",
    "influencers_tiktokvideodailymetric",
    "influencers_tiktokvideoproduct",
    "influencers_tiktokvideosyncbatch",
    "influencers_videoresult",
    "influencers_externalsourcerecord",
)

ACCOUNT_COLUMNS = {
    "created_by_id",
    "actor_id",
    "dispatcher_id",
    "owner_id",
    "deleted_by_id",
}
STRUCTURAL_SAMPLE_LIMIT = 20
DEFAULT_BATCH_SIZE = 1000
SAFE_NAME = re.compile(r"^[A-Za-z0-9_]+$")
MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð", "å", "æ", "ç", "�")


class MappingFailure(RuntimeError):
    """A required natural-key mapping was missing or ambiguous."""


def _load_driver():
    try:
        import MySQLdb  # type: ignore

        return MySQLdb
    except ImportError:
        try:
            import pymysql  # type: ignore

            return pymysql
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise SystemExit(
                "需要 mysqlclient(MySQLdb) 或 PyMySQL；请在后端容器内运行本脚本。"
            ) from exc


def effective_db_credentials(args: argparse.Namespace, role: str) -> dict[str, Any]:
    """Return role-specific connection settings with generic fallbacks."""

    if role not in {"stage", "target"}:
        raise ValueError(f"unknown database role: {role}")
    return {
        "host": getattr(args, f"{role}_db_host") or args.db_host,
        "port": getattr(args, f"{role}_db_port")
        if getattr(args, f"{role}_db_port") is not None
        else args.db_port,
        "user": getattr(args, f"{role}_db_user")
        if getattr(args, f"{role}_db_user") is not None
        else args.db_user,
        "password": getattr(args, f"{role}_db_password")
        if getattr(args, f"{role}_db_password") is not None
        else args.db_password,
    }


def db_connect(
    args: argparse.Namespace,
    database: str,
    readonly: bool,
    role: str = "target",
):
    if not SAFE_NAME.fullmatch(database):
        raise SystemExit(f"非法数据库名: {database!r}")
    driver = _load_driver()
    credentials = effective_db_credentials(args, role)
    kwargs = {
        "host": credentials["host"],
        "port": credentials["port"],
        "user": credentials["user"],
        "passwd": credentials["password"],
        "db": database,
        "charset": "utf8mb4",
        "autocommit": False,
    }
    conn = driver.connect(**kwargs)
    with conn.cursor() as cur:
        cur.execute("SET SESSION time_zone = '+00:00'")
        if readonly:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
    conn.rollback()
    return conn


def qident(name: str) -> str:
    if not SAFE_NAME.fullmatch(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


def chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def clean_scalar(value: Any) -> Any:
    """Convert driver-specific values only where comparisons need stability."""

    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def read_map_file(
    path: str | None, first_column: str, second_column: str
) -> dict[str, str]:
    if not path:
        return {}
    result: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {first_column, second_column}
        if not reader.fieldnames or not expected.issubset(set(reader.fieldnames)):
            raise SystemExit(
                f"{path}: CSV 必须包含列 {first_column},{second_column}"
            )
        for line_no, row in enumerate(reader, 2):
            left = (row.get(first_column) or "").strip()
            right = (row.get(second_column) or "").strip()
            if not left or not right:
                raise SystemExit(f"{path}:{line_no}: 映射键和值都不能为空")
            previous = result.get(left)
            if previous is not None and previous != right:
                raise SystemExit(f"{path}:{line_no}: 同一映射键出现冲突值")
            result[left] = right
    return result


def key_for(value: Any) -> str:
    return "" if value is None else str(clean_scalar(value)).strip()


def is_suspect_text(value: Any) -> bool:
    """Return whether a display value is replacement text or mojibake.

    The handoff snapshot contains names decoded with the wrong character set
    in some rows.  We only reject values with strong evidence of corruption:
    the Unicode replacement character, a value made entirely of question
    marks, or a reversible cp1252/latin1-to-UTF-8 mojibake pattern.  Normal
    Chinese, English, punctuation, and accented names remain valid.
    """

    text = key_for(value)
    if not text:
        return False
    if "\ufffd" in text or "\x00" in text:
        return True
    if text.count("?") >= 2 and not re.search(r"[A-Za-z\u3400-\u9fff]", text):
        return True

    def cjk_count(candidate: str) -> int:
        return len(re.findall(r"[\u3400-\u9fff]", candidate))

    source_cjk = cjk_count(text)
    for encoding in ("cp1252", "latin1"):
        try:
            repaired = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != text and cjk_count(repaired) > source_cjk:
            return True
    return (
        sum(text.count(marker) for marker in MOJIBAKE_MARKERS) >= 2
        and source_cjk == 0
    )


def _validated_name(
    value: Any,
    reporter: "Reporter",
    table: str,
    field: str,
    *,
    source: bool,
) -> str:
    text = key_for(value)
    if not text:
        return ""
    if is_suspect_text(text):
        origin = "source" if source else "target"
        reporter.issue(f"{table}:{field}:{origin}_mojibake")
        return ""
    return text


def choose_display_name(
    source_value: Any,
    target_candidates: Sequence[tuple[str, Any]],
    reporter: "Reporter",
    table: str,
    field: str,
) -> str:
    """Prefer tenant-1 catalog names and never write a suspect source name."""

    source_name = _validated_name(
        source_value, reporter, table, field, source=True
    )
    for origin, candidate in target_candidates:
        target_name = _validated_name(
            candidate, reporter, table, field, source=False
        )
        if target_name:
            reporter.issue(f"{table}:{field}:target_{origin}_used")
            return target_name
    if source_name:
        return source_name
    reporter.issue(f"{table}:{field}:unresolved")
    return ""


def _row_to_dict(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    """Normalize tuple rows and DictCursor rows from streaming cursors."""

    if isinstance(row, MappingABC):
        return dict(row)
    return dict(zip(columns, row))


class Reporter:
    def __init__(self, apply: bool, report_path: str | None):
        self.apply = apply
        self.report_path = report_path
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.tables: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "source": 0,
                "attempted": 0,
                "skipped": 0,
                "existing_or_unchanged": 0,
                "inserted_estimate": 0,
            }
        )
        self.issues: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "samples": []}
        )
        self.notes: list[str] = []

    def source(self, table: str, count: int) -> None:
        self.tables[table]["source"] += count

    def attempted(self, table: str, count: int) -> None:
        self.tables[table]["attempted"] += count

    def issue(self, category: str, sample: Any = None, count: int = 1) -> None:
        issue = self.issues[category]
        issue["count"] += count
        if sample is not None and len(issue["samples"]) < STRUCTURAL_SAMPLE_LIMIT:
            issue["samples"].append(str(sample)[:160])

    def skipped(self, table: str, reason: str, sample: Any = None) -> None:
        self.tables[table]["skipped"] += 1
        # Samples are limited to operational keys; influencer handles or
        # contact values are deliberately never written to the report.
        self.issue(f"{table}:{reason}", sample=sample)

    def add_note(self, message: str) -> None:
        self.notes.append(message)

    def finish(self, args: argparse.Namespace, target_counts: Mapping[str, int]) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "release_version": "2.44.41",
            "mode": "apply" if self.apply else "dry-run",
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_database": args.stage_db,
            "target_database": args.target_db,
            "source_tenant_id": args.source_tenant_id,
            "target_tenant_code": args.tenant_code,
            "batch_size": args.batch_size,
            "target_counts_after_or_observed": dict(target_counts),
            "tables": dict(self.tables),
            "issues": dict(self.issues),
            "notes": self.notes,
            "safety": {
                "target_primary_keys_copied": False,
                "foreign_keys_disabled": False,
                "delete_or_truncate_used": False,
                "tenant_scoped": True,
                "required_relation_unmatched_is_skipped": True,
            },
        }
        if self.report_path:
            output = Path(self.report_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        return payload


class Migrator:
    def __init__(
        self,
        args: argparse.Namespace,
        source,
        target,
        reporter: Reporter,
        user_map: Mapping[str, str],
        store_map: Mapping[str, str],
        platform_map: Mapping[str, str],
        spu_map: Mapping[str, str],
    ):
        self.args = args
        self.source = source
        self.target = target
        self.report = reporter
        self.user_map = dict(user_map)
        self.store_map = dict(store_map)
        self.platform_map = dict(platform_map)
        self.spu_map = dict(spu_map)
        self.target_tenant_id: int | None = None
        self.user_ids: dict[str, int] = {}
        self.store_ids: dict[str, int] = {}
        self.store_source_codes: dict[str, str] = {}
        self.platform_codes: dict[str, str] = {}
        self.spu_ids: dict[str, int] = {}
        self.spu_names: dict[int, str] = {}
        self.sku_ids: dict[str, int | None] = {}
        self.sku_names: dict[int, str] = {}
        self.sku_spu_names: dict[int, str] = {}
        self.listing_name_candidates: dict[
            tuple[int, str], list[tuple[str, str]]
        ] = {}
        self.influencer_ids: dict[str, int] = {}
        self.influencer_source_ids: dict[int, int] = {}
        self.listing_ids: dict[tuple[int, str, str], int] = {}
        self.task_ids: dict[str, int] = {}
        self.target_ids: dict[tuple[int, int], int] = {}
        self.fulfillment_ids: dict[str, int] = {}
        self.batch_ids: dict[str, int] = {}

    def _fetchall(self, conn, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor_class = getattr(_load_driver(), "cursors", None)
        # Both mysqlclient and PyMySQL expose DictCursor.  Importing the class
        # from the connection's driver keeps this script usable in containers.
        if cursor_class is not None and hasattr(cursor_class, "DictCursor"):
            with conn.cursor(cursor_class.DictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [item[0] for item in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def _fetchone(self, conn, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self._fetchall(conn, sql, params)
        return rows[0] if rows else None

    def _iter_source(self, table: str) -> Iterator[dict[str, Any]]:
        sql = (
            f"SELECT * FROM {qident(self.args.stage_db)}.{qident(table)} "
            "WHERE tenant_id = %s ORDER BY id"
        )
        cursor_class = getattr(_load_driver(), "cursors", None)
        if cursor_class is not None and hasattr(cursor_class, "SSDictCursor"):
            cur = self.source.cursor(cursor_class.SSDictCursor)
        else:
            cur = self.source.cursor()
        try:
            cur.execute(sql, (self.args.source_tenant_id,))
            columns = [item[0] for item in cur.description]
            for row in cur:
                # PyMySQL/mysqlclient SSDictCursor yields a mapping; the
                # default streaming cursor yields a tuple.  Iterating a
                # mapping would otherwise zip column names with its keys.
                yield _row_to_dict(row, columns)
        finally:
            cur.close()

    def _count_target(self, table: str) -> int:
        row = self._fetchone(
            self.target,
            f"SELECT COUNT(*) AS n FROM {qident(self.args.target_db)}.{qident(table)} "
            "WHERE tenant_id = %s",
            (self.target_tenant_id,),
        )
        return int(row["n"]) if row else 0

    def _resolve_tenant(self) -> None:
        rows = self._fetchall(
            self.target,
            f"SELECT id, code FROM {qident(self.args.target_db)}.tenants_tenant "
            "WHERE code = %s",
            (self.args.tenant_code,),
        )
        if len(rows) != 1:
            raise SystemExit(
                f"目标租户 code={self.args.tenant_code!r} 未唯一匹配；不会写入正式库"
            )
        self.target_tenant_id = int(rows[0]["id"])

    def _resolve_platforms(self) -> None:
        source_rows = self._fetchall(
            self.source,
            f"SELECT DISTINCT TRIM(platform) AS source_platform "
            f"FROM {qident(self.args.stage_db)}.influencers_influencer "
            "WHERE tenant_id = %s AND TRIM(platform) <> ''",
            (self.args.source_tenant_id,),
        )
        source_codes = [key_for(row["source_platform"]) for row in source_rows]
        target_codes = sorted(
            {self.platform_map.get(code, code) for code in source_codes}
        )
        if not target_codes:
            return
        rows = self._fetchall(
            self.target,
            f"SELECT code FROM {qident(self.args.target_db)}.masterdata_platformmaster "
            f"WHERE tenant_id = %s AND code IN ({placeholders(len(target_codes))})",
            (self.target_tenant_id, *target_codes),
        )
        available = {key_for(row["code"]) for row in rows}
        for source_code in source_codes:
            target_code = self.platform_map.get(source_code, source_code)
            if target_code in available:
                self.platform_codes[source_code] = target_code
            else:
                self.report.issues[f"platform:{source_code}:target_code_not_found"] = {
                    "count": 1,
                    "samples": [target_code],
                }

    def _resolve_users(self) -> None:
        usernames = set(self.user_map.values())
        if self.args.target_admin_username:
            usernames.add(self.args.target_admin_username)
        if not usernames:
            self.report.add_note(
                "交接包不含 accounts_customuser；请提供 --user-map-file，或显式列出 --source-admin-ids。"
            )
            return
        marks = placeholders(len(usernames))
        rows = self._fetchall(
            self.target,
            f"SELECT id, username FROM {qident(self.args.target_db)}.accounts_customuser "
            f"WHERE username IN ({marks})",
            tuple(usernames),
        )
        self.user_ids = {str(row["username"]): int(row["id"]) for row in rows}
        missing = sorted(usernames - set(self.user_ids))
        if missing:
            raise SystemExit("目标用户映射不存在；不会猜测用户绑定")
        admin_id = (
            self.user_ids.get(self.args.target_admin_username)
            if self.args.target_admin_username
            else None
        )
        if admin_id is not None:
            for source_id in self.args.source_admin_ids:
                self.user_map.setdefault(str(source_id), self.args.target_admin_username)

    def _derive_store_codes(self) -> None:
        if self.store_map:
            return
        if not self.args.derive_store_map:
            self.report.add_note(
                "交接包不含 masterdata_storemaster；请提供 --store-map-file，"
                "或使用 --derive-store-map 按 source 店铺ID+shop_abbr 推导并校验。"
            )
            return
        rows = self._fetchall(
            self.source,
            f"SELECT store_id, shop_abbr, COUNT(*) AS n "
            f"FROM {qident(self.args.stage_db)}.influencers_bdsampleattributionsnapshot "
            "WHERE tenant_id = %s AND TRIM(shop_abbr) <> '' "
            "GROUP BY store_id, shop_abbr",
            (self.args.source_tenant_id,),
        )
        candidates: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            candidates[str(row["store_id"])].add(str(row["shop_abbr"]).strip())
        for source_id, codes in candidates.items():
            if len(codes) == 1:
                self.store_map[source_id] = next(iter(codes))
            else:
                self.report.issues[f"store:{source_id}:ambiguous_code"] = {
                    "count": 1,
                    "samples": [],
                }
        if not self.store_map:
            self.report.add_note("未能从 shop_abbr 推导任何店铺自然键")

    def _resolve_stores(self) -> None:
        self._derive_store_codes()
        codes = sorted(set(self.store_map.values()))
        if not codes:
            return
        rows = self._fetchall(
            self.target,
            f"SELECT s.id, s.code, s.platform_id, p.code AS platform_code "
            f"FROM {qident(self.args.target_db)}.masterdata_storemaster s "
            f"LEFT JOIN {qident(self.args.target_db)}.masterdata_platformmaster p "
            "ON p.id = s.platform_id AND p.tenant_id = s.tenant_id "
            f"WHERE s.tenant_id = %s AND s.code IN ({placeholders(len(codes))})",
            (self.target_tenant_id, *codes),
        )
        by_code = defaultdict(list)
        for row in rows:
            by_code[str(row["code"])].append(row)
        for source_id, code in self.store_map.items():
            matches = by_code.get(code, [])
            if len(matches) == 1:
                platform_code = key_for(matches[0].get("platform_code"))
                if not platform_code:
                    self.report.issues[f"store:{source_id}:target_platform_not_found"] = {
                        "count": 1,
                        "samples": [code],
                    }
                    continue
                self.store_ids[source_id] = int(matches[0]["id"])
                self.store_source_codes[source_id] = platform_code
            elif not matches:
                self.report.issues[f"store:{source_id}:target_code_not_found"] = {
                    "count": 1,
                    "samples": [code],
                }
            else:
                self.report.issues[f"store:{source_id}:target_code_ambiguous"] = {
                    "count": len(matches),
                    "samples": [code],
                }

    def _resolve_spus(self) -> None:
        codes = sorted(set(self.spu_map.values()))
        if not codes:
            return
        rows = self._fetchall(
            self.target,
            f"SELECT id, spu_code, legacy_spu_code, product_name FROM {qident(self.args.target_db)}.products_productspu "
            f"WHERE tenant_id = %s AND (spu_code IN ({placeholders(len(codes))}) "
            f"OR legacy_spu_code IN ({placeholders(len(codes))}))",
            (self.target_tenant_id, *codes, *codes),
        )
        by_code: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            self.spu_names[int(row["id"])] = key_for(row.get("product_name"))
            for key in (row["spu_code"], row["legacy_spu_code"]):
                if key:
                    by_code[str(key)].append(int(row["id"]))
        for source_id, code in self.spu_map.items():
            matches = sorted(set(by_code.get(code, [])))
            if len(matches) == 1:
                self.spu_ids[source_id] = matches[0]
            elif not matches:
                self.report.issues[f"spu:{source_id}:target_code_not_found"] = {
                    "count": 1,
                    "samples": [code],
                }
            else:
                self.report.issues[f"spu:{source_id}:target_code_ambiguous"] = {
                    "count": len(matches),
                    "samples": [code],
                }

    def _resolve_skus(self) -> None:
        rows = self._fetchall(
            self.target,
            f"SELECT s.id, s.sku_code, s.legacy_sku_code, s.product_name, "
            f"s.spu_id, p.product_name AS spu_product_name "
            f"FROM {qident(self.args.target_db)}.products_productsku s "
            f"LEFT JOIN {qident(self.args.target_db)}.products_productspu p "
            "ON p.id = s.spu_id AND p.tenant_id = s.tenant_id "
            "WHERE s.tenant_id = %s",
            (self.target_tenant_id,),
        )
        by_new: dict[str, list[int]] = defaultdict(list)
        by_old: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            sku_name = key_for(row.get("product_name"))
            spu_name = key_for(row.get("spu_product_name"))
            sku_id = int(row["id"])
            self.sku_names[sku_id] = sku_name
            self.sku_spu_names[sku_id] = spu_name
            if row.get("spu_id") is not None and spu_name and not self.spu_names.get(int(row["spu_id"])):
                self.spu_names[int(row["spu_id"])] = spu_name
            if row["sku_code"]:
                by_new[str(row["sku_code"])].append(int(row["id"]))
            if row["legacy_sku_code"]:
                by_old[str(row["legacy_sku_code"])].append(int(row["id"]))
        self.sku_ids = {}
        for table in ("influencers_skupricesnapshot", "influencers_sampleitem"):
            for row in self._iter_source(table):
                value = key_for(row.get("external_sku") or row.get("requested_sku"))
                if not value or value in self.sku_ids:
                    continue
                matches = sorted(set(by_new.get(value, []))) or sorted(
                    set(by_old.get(value, []))
                )
                self.sku_ids[value] = matches[0] if len(matches) == 1 else None
                if len(matches) > 1:
                    self.report.issues[f"sku:{value}:ambiguous"] = {
                        "count": len(matches),
                        "samples": [],
                    }
                elif not matches:
                    self.report.issues[f"sku:{value}:not_found"] = {
                        "count": 1,
                        "samples": [],
                    }

    def _load_platform_listing_names(
        self, keys: Sequence[tuple[int, str, str]]
    ) -> None:
        """Load target platform titles and catalog names in bounded batches."""

        self.listing_name_candidates.clear()
        unique_keys = list(dict.fromkeys(keys))
        for batch in chunks(unique_keys, 200):
            terms = " OR ".join(
                ["(d.store_id = %s AND d.platform_product_id = %s)"] * len(batch)
            )
            params: list[Any] = [self.target_tenant_id]
            for store_id, _site_code, product_id in batch:
                params.extend([store_id, product_id])
            rows = self._fetchall(
                self.target,
                f"SELECT d.store_id, d.platform_product_id, d.title, d.internal_sku_id, "
                f"s.product_name AS sku_product_name, p.product_name AS spu_product_name "
                f"FROM {qident(self.args.target_db)}.listings_platformproductdetail d "
                f"LEFT JOIN {qident(self.args.target_db)}.products_productsku s "
                "ON s.id = d.internal_sku_id AND s.tenant_id = d.tenant_id "
                f"LEFT JOIN {qident(self.args.target_db)}.products_productspu p "
                "ON p.id = s.spu_id AND p.tenant_id = s.tenant_id "
                f"WHERE d.tenant_id = %s AND ({terms})",
                params,
            )
            for row in rows:
                key = (int(row["store_id"]), key_for(row["platform_product_id"]))
                candidates = self.listing_name_candidates.setdefault(key, [])
                for origin, value in (
                    ("title", row.get("title")),
                    ("sku", row.get("sku_product_name")),
                    ("spu", row.get("spu_product_name")),
                ):
                    text = key_for(value)
                    if text and (origin, text) not in candidates:
                        candidates.append((origin, text))

    def _resolve_influencers(self) -> None:
        target_rows = self._fetchall(
            self.target,
            f"SELECT id, code, platform, handle FROM {qident(self.args.target_db)}.influencers_influencer "
            "WHERE tenant_id = %s",
            (self.target_tenant_id,),
        )
        by_code = {str(row["code"]): int(row["id"]) for row in target_rows}
        by_handle: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in target_rows:
            if row["handle"]:
                by_handle[(str(row["platform"]).lower(), str(row["handle"]).lower())].append(
                    int(row["id"])
                )
        pending: list[tuple[Any, ...]] = []
        pending_codes: list[str] = []
        seen_codes: set[str] = set()
        rows = list(self._iter_source("influencers_influencer"))
        self.report.source("influencers_influencer", len(rows))
        for row in rows:
            source_id = int(row["id"])
            code = key_for(row["code"])
            source_platform = key_for(row["platform"])
            platform_code = self.platform_codes.get(source_platform)
            if not platform_code:
                self.report.skipped(
                    "influencers_influencer",
                    "platform:unmapped",
                    source_platform or "blank",
                )
                continue
            if not code or code in seen_codes:
                if code:
                    self.influencer_source_ids[source_id] = by_code.get(code, 0)
                continue
            seen_codes.add(code)
            if code in by_code:
                self.influencer_ids[code] = by_code[code]
                self.influencer_source_ids[source_id] = by_code[code]
                continue
            handle_key = (
                platform_code.lower(),
                str(row["handle"]).lower(),
            )
            candidates = by_handle.get(handle_key, [])
            if len(candidates) == 1:
                self.influencer_ids[code] = candidates[0]
                self.influencer_source_ids[source_id] = candidates[0]
                continue
            if len(candidates) > 1:
                self.report.skipped(
                    "influencers_influencer", "platform_handle_ambiguous", "redacted"
                )
                continue
            pending_codes.append(code)
            pending.append(
                (
                    code,
                    row["name"],
                    platform_code,
                    row["handle"],
                    row["category"],
                    row["follower_count"],
                    row["contact_name"],
                    row["contact_phone"],
                    row["contact_email"],
                    row["cooperation_status"],
                    row["status"],
                    row["notes"],
                    row["created_at"],
                    row["updated_at"],
                    self.target_tenant_id,
                )
            )
        self.report.attempted("influencers_influencer", len(pending))
        self._insert(
            "influencers_influencer",
            (
                "code",
                "name",
                "platform",
                "handle",
                "category",
                "follower_count",
                "contact_name",
                "contact_phone",
                "contact_email",
                "cooperation_status",
                "status",
                "notes",
                "created_at",
                "updated_at",
                "tenant_id",
            ),
            pending,
        )
        if pending_codes:
            if self.report.apply:
                marks = placeholders(len(pending_codes))
                fresh = self._fetchall(
                    self.target,
                    f"SELECT id, code FROM {qident(self.args.target_db)}.influencers_influencer "
                    f"WHERE tenant_id = %s AND code IN ({marks})",
                    (self.target_tenant_id, *pending_codes),
                )
                for row in fresh:
                    self.influencer_ids[str(row["code"])] = int(row["id"])
            else:
                # Dry-run uses negative sentinels only in memory so the
                # downstream mapping audit can continue without any target
                # write or fabricated target primary key.
                for index, code in enumerate(pending_codes, 1):
                    self.influencer_ids[code] = -index
        for row in rows:
            code = key_for(row["code"])
            target_id = self.influencer_ids.get(code)
            if target_id:
                self.influencer_source_ids[int(row["id"])] = target_id
        self.report.tables["influencers_influencer"]["inserted_estimate"] = len(
            pending_codes
        )

    def _source_fk(self, source_id: Any, table: str, field: str, required: bool) -> int | None:
        if source_id is None:
            if required:
                self.report.skipped(table, f"{field}:null")
            return None
        key = str(source_id)
        username = self.user_map.get(key)
        target_id = self.user_ids.get(username) if username else None
        if target_id is None:
            self.report.skipped(table, f"{field}:unmapped")
        return target_id

    def _store_fk(self, source_id: Any, table: str, required: bool = True) -> int | None:
        if source_id is None:
            if required:
                self.report.skipped(table, "store:null")
            return None
        target_id = self.store_ids.get(str(source_id))
        if target_id is None:
            self.report.skipped(table, "store:unmapped")
        return target_id

    def _spu_fk(self, source_id: Any, table: str) -> int | None:
        if source_id is None:
            return None
        target_id = self.spu_ids.get(str(source_id))
        if target_id is None:
            self.report.skipped(table, "spu:unmapped", str(source_id))
        return target_id

    def _sku_fk(self, code: Any, table: str) -> int | None:
        value = key_for(code)
        if not value:
            return None
        target_id = self.sku_ids.get(value)
        if target_id is None:
            self.report.skipped(table, "sku:unmapped")
        return target_id

    def _insert(
        self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        if not rows:
            return
        table_sql = f"{qident(self.args.target_db)}.{qident(table)}"
        cols_sql = ", ".join(qident(column) for column in columns)
        sql = (
            f"INSERT INTO {table_sql} ({cols_sql}) VALUES "
            f"({placeholders(len(columns))}) ON DUPLICATE KEY UPDATE id = id"
        )
        for batch in chunks(list(rows), self.args.batch_size):
            if not self.report.apply:
                continue
            with self.target.cursor() as cur:
                cur.executemany(sql, batch)
                # MySQL reports 1 for an inserted row and 0 for the
                # id=id no-op duplicate with the default client flags.
                # Keep this as an estimate because connector flags can alter
                # rowcount semantics; the natural-key operation remains
                # idempotent either way.
                affected = int(cur.rowcount)
            self.report.tables[table]["inserted_estimate"] += max(
                0, min(len(batch), affected)
            )
            self.report.tables[table]["existing_or_unchanged"] += max(
                0, len(batch) - affected
            )
            self.target.commit()

    def _map_batch_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.report.source(table, len(rows))
        self.report.attempted(table, 0)

    def _process_profiles(self) -> None:
        table = "influencers_influencerprofile"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        for row in rows:
            influencer_id = self.influencer_source_ids.get(int(row["influencer_id"]))
            if influencer_id is None:
                self.report.skipped(table, "influencer:unmapped")
                continue
            out.append(
                (
                    row["display_name"],
                    row["external_influencer_id"],
                    row["level"],
                    row["tier"],
                    row["average_video_views"],
                    row["average_live_views"],
                    row["is_active"],
                    row["market"],
                    row["platforms"],
                    row["content_types"],
                    row["profile_url"],
                    row["duplicate_reason"],
                    row["product_cooperation_count"],
                    row["first_cooperation_at"],
                    row["cooperation_count"],
                    row["completed_cooperation_count"],
                    row["fulfilled_cooperation_count"],
                    row["fulfillment_rate"],
                    row["content_completion_rate"],
                    row["historical_gmv"],
                    row["historical_orders"],
                    row["historical_performance"],
                    row["profile_notes"],
                    row["created_at"],
                    row["updated_at"],
                    influencer_id,
                    self.target_tenant_id,
                )
            )
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "display_name",
                "external_influencer_id",
                "level",
                "tier",
                "average_video_views",
                "average_live_views",
                "is_active",
                "market",
                "platforms",
                "content_types",
                "profile_url",
                "duplicate_reason",
                "product_cooperation_count",
                "first_cooperation_at",
                "cooperation_count",
                "completed_cooperation_count",
                "fulfilled_cooperation_count",
                "fulfillment_rate",
                "content_completion_rate",
                "historical_gmv",
                "historical_orders",
                "historical_performance",
                "profile_notes",
                "created_at",
                "updated_at",
                "influencer_id",
                "tenant_id",
            ),
            out,
        )

    def _process_contacts(self) -> None:
        for table, kind in (
            ("influencers_influencercontact", "contact"),
            ("influencers_influencerrestriction", "restriction"),
            ("influencers_influencerrestrictevent", "restriction_event"),
        ):
            rows = list(self._iter_source(table))
            self.report.source(table, len(rows))
            out = []
            for row in rows:
                influencer_id = self.influencer_source_ids.get(int(row["influencer_id"]))
                if influencer_id is None:
                    self.report.skipped(table, "influencer:unmapped")
                    continue
                common = [row[column] for column in (
                    {
                        "contact": ("channel", "value", "label", "is_primary", "is_active", "created_at", "updated_at"),
                        "restriction": ("is_blacklisted", "reason", "created_at", "updated_at"),
                        "restriction_event": ("action", "reason", "occurred_at", "source", "created_at"),
                    }[kind]
                )]
                account_field = {
                    "contact": "created_by_id",
                    "restriction": "created_by_id",
                    "restriction_event": "actor_id",
                }[kind]
                actor_id = self._source_fk(row[account_field], table, account_field, True)
                if actor_id is None:
                    continue
                out.append((*common, actor_id, influencer_id, self.target_tenant_id))
            self.report.attempted(table, len(out))
            columns = {
                "contact": (
                    "channel", "value", "label", "is_primary", "is_active", "created_at", "updated_at",
                    "created_by_id", "influencer_id", "tenant_id",
                ),
                "restriction": (
                    "is_blacklisted", "reason", "created_at", "updated_at",
                    "created_by_id", "influencer_id", "tenant_id",
                ),
                "restriction_event": (
                    "action", "reason", "occurred_at", "source", "created_at",
                    "actor_id", "influencer_id", "tenant_id",
                ),
            }[kind]
            if kind == "restriction_event" and out:
                # Restriction history has no database UNIQUE constraint.  A
                # repeat import must therefore deduplicate by the documented
                # natural key instead of relying on the surrogate id.
                existing = self._fetchall(
                    self.target,
                    f"SELECT influencer_id, action, occurred_at "
                    f"FROM {qident(self.args.target_db)}.{qident(table)} "
                    "WHERE tenant_id = %s",
                    (self.target_tenant_id,),
                )
                existing_keys = {
                    (str(row["influencer_id"]), str(row["action"]), str(row["occurred_at"]))
                    for row in existing
                }
                unique_out = []
                for item in out:
                    key = (str(item[6]), str(item[0]), str(item[2]))
                    if key in existing_keys:
                        self.report.tables[table]["existing_or_unchanged"] += 1
                        continue
                    existing_keys.add(key)
                    unique_out.append(item)
                out = unique_out
            self._insert(table, columns, out)

    def _process_listings(self) -> None:
        table = "influencers_storeproductlisting"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        source_keys = []
        self.source_listing_ids: dict[int, tuple[int, str, str]] = {}
        candidate_keys: list[tuple[int, str, str]] = []
        for row in rows:
            store_id = self.store_ids.get(str(row["store_id"]))
            if store_id is None:
                continue
            site_code = key_for(row["site_code"])
            external_product_id = key_for(row["external_product_id"])
            candidate_keys.append((store_id, site_code, external_product_id))
        self._load_platform_listing_names(candidate_keys)
        for row in rows:
            store_id = self._store_fk(row["store_id"], table)
            if store_id is None:
                continue
            spu_id = self._spu_fk(row.get("spu_id"), table)
            site_code = key_for(row["site_code"])
            external_product_id = key_for(row["external_product_id"])
            target_candidates = list(
                self.listing_name_candidates.get((store_id, external_product_id), [])
            )
            if spu_id is not None:
                target_candidates.append(("spu", self.spu_names.get(spu_id, "")))
            product_name = choose_display_name(
                row.get("product_name"),
                target_candidates,
                self.report,
                table,
                "product_name",
            )
            out.append(
                (
                    external_product_id, row["parent_sku"], product_name,
                    site_code, row["source"], row["source_updated_at"],
                    row["created_at"], row["updated_at"], spu_id, store_id,
                    self.target_tenant_id,
                )
            )
            source_keys.append((store_id, site_code, external_product_id))
            self.source_listing_ids[int(row["id"])] = (
                store_id,
                site_code,
                external_product_id,
            )
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "external_product_id", "parent_sku", "product_name", "site_code",
                "source", "source_updated_at", "created_at", "updated_at",
                "spu_id", "store_id", "tenant_id",
            ),
            out,
        )
        self._refresh_listings(source_keys)

    def _refresh_listings(self, keys: Sequence[tuple[int, str, str]]) -> None:
        self.listing_ids.clear()
        if not keys:
            return
        if not self.report.apply:
            for index, key in enumerate(dict.fromkeys(keys), 1):
                self.listing_ids[key] = -index
            return
        by_store: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for store_id, site, external in keys:
            by_store[store_id].append((site, external))
        for store_id, pairs in by_store.items():
            terms = " OR ".join(["(site_code = %s AND external_product_id = %s)"] * len(pairs))
            params: list[Any] = [self.target_tenant_id, store_id]
            for site, external in pairs:
                params.extend([site, external])
            rows = self._fetchall(
                self.target,
                f"SELECT id, store_id, site_code, external_product_id "
                f"FROM {qident(self.args.target_db)}.influencers_storeproductlisting "
                f"WHERE tenant_id = %s AND store_id = %s AND ({terms})",
                params,
            )
            for row in rows:
                self.listing_ids[
                    (int(row["store_id"]), str(row["site_code"]), str(row["external_product_id"]))
                ] = int(row["id"])

    def _process_prices(self) -> None:
        table = "influencers_skupricesnapshot"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        for row in rows:
            listing_id = self._listing_for_source_id(row["listing_id"])
            if listing_id is None:
                self.report.skipped(table, "listing:unmapped")
                continue
            sku_id = self._sku_fk(row["external_sku"], table)
            variant_name = choose_display_name(
                row.get("variant_name"),
                (
                    [
                        ("sku", self.sku_names.get(sku_id, "")),
                        ("spu", self.sku_spu_names.get(sku_id, "")),
                    ]
                    if sku_id
                    else []
                ),
                self.report,
                table,
                "variant_name",
            )
            out.append(
                (
                    row["external_sku"], row["variant_id"], variant_name,
                    row["original_price"], row["promotion_price"], row["effective_price"],
                    row["inbound_cost"], row["currency"], row["stock"], row["source"],
                    row["source_updated_at"], row["cost_updated_at"], row["imported_at"],
                    sku_id, self.target_tenant_id, listing_id,
                )
            )
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "external_sku", "variant_id", "variant_name", "original_price",
                "promotion_price", "effective_price", "inbound_cost", "currency",
                "stock", "source", "source_updated_at", "cost_updated_at",
                "imported_at", "sku_id", "tenant_id", "listing_id",
            ),
            out,
        )

    def _listing_for_source_id(self, source_id: Any) -> int | None:
        # Source listing IDs are not copied.  Resolve them using source row
        # natural keys, retained in this map after _process_listings.
        source_key = getattr(self, "source_listing_ids", {}).get(int(source_id))
        if source_key is not None:
            return self.listing_ids.get(source_key)
        row = self._fetchone(
            self.source,
            f"SELECT store_id, site_code, external_product_id "
            f"FROM {qident(self.args.stage_db)}.influencers_storeproductlisting "
            "WHERE id = %s AND tenant_id = %s",
            (source_id, self.args.source_tenant_id),
        )
        if not row:
            return None
        target_store = self.store_ids.get(str(row["store_id"]))
        if target_store is None:
            return None
        return self.listing_ids.get(
            (target_store, str(row["site_code"]), str(row["external_product_id"]))
        )

    def _process_tasks(self) -> None:
        table = "influencers_outreachtask"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        source_to_key: dict[int, str] = {}
        for row in rows:
            dispatcher_id = self._source_fk(row["dispatcher_id"], table, "dispatcher_id", True)
            owner_id = self._source_fk(row["owner_id"], table, "owner_id", True)
            store_id = self._store_fk(row["store_id"], table)
            if dispatcher_id is None or owner_id is None or store_id is None:
                continue
            influencer_id = (
                self.influencer_source_ids.get(int(row["influencer_id"]))
                if row["influencer_id"] is not None
                else None
            )
            if row["influencer_id"] is not None and influencer_id is None:
                self.report.skipped(table, "influencer:unmapped")
                continue
            spu_id = self._spu_fk(row.get("spu_id"), table)
            out.append(
                (
                    row["task_no"], row["status"], row["started_at"], row["finalized_at"],
                    row["source"], row["external_id"], row["version"], row["notes"],
                    row["created_at"], row["updated_at"], dispatcher_id, influencer_id,
                    owner_id, spu_id, store_id, self.target_tenant_id, row["deleted_at"],
                    row["dispatch_time"], row["external_product_id"], row["is_deleted"],
                    row["outreach_at"], row["sku_prefix"], row["target_count"],
                    row["task_name"], row["product_name_snapshot"], row["product_match_status"],
                    row["product_match_source"], row["product_matched_at"], row["priority"],
                )
            )
            source_to_key[int(row["id"])] = str(row["task_no"])
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "task_no", "status", "started_at", "finalized_at", "source", "external_id",
                "version", "notes", "created_at", "updated_at", "dispatcher_id",
                "influencer_id", "owner_id", "spu_id", "store_id", "tenant_id", "deleted_at",
                "dispatch_time", "external_product_id", "is_deleted", "outreach_at",
                "sku_prefix", "target_count", "task_name", "product_name_snapshot",
                "product_match_status", "product_match_source", "product_matched_at", "priority",
            ),
            out,
        )
        if source_to_key and self.report.apply:
            marks = placeholders(len(source_to_key))
            rows2 = self._fetchall(
                self.target,
                f"SELECT id, task_no FROM {qident(self.args.target_db)}.influencers_outreachtask "
                f"WHERE tenant_id = %s AND task_no IN ({marks})",
                (self.target_tenant_id, *source_to_key.values()),
            )
            self.task_ids = {str(row["task_no"]): int(row["id"]) for row in rows2}
            self.source_task_ids = {
                source_id: self.task_ids.get(task_no)
                for source_id, task_no in source_to_key.items()
                if self.task_ids.get(task_no)
            }
        elif source_to_key:
            self.task_ids = {
                task_no: -index
                for index, task_no in enumerate(dict.fromkeys(source_to_key.values()), 1)
            }
            self.source_task_ids = {
                source_id: self.task_ids.get(task_no)
                for source_id, task_no in source_to_key.items()
                if self.task_ids.get(task_no)
            }
        else:
            self.source_task_ids = {}

    def _process_targets(self) -> None:
        table = "influencers_outreachtarget"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        source_target_keys: dict[int, tuple[int, int]] = {}
        for row in rows:
            task_id = getattr(self, "source_task_ids", {}).get(int(row["task_id"]))
            influencer_id = self.influencer_source_ids.get(int(row["influencer_id"]))
            if task_id is None or influencer_id is None:
                self.report.skipped(table, "parent:unmapped")
                continue
            out.append(
                (
                    row["first_linked_at"], row["outreach_result"], row["version"], row["notes"],
                    row["is_deleted"], row["deleted_at"], row["created_at"], row["updated_at"],
                    influencer_id, task_id, self.target_tenant_id,
                )
            )
            source_target_keys[int(row["id"])] = (task_id, influencer_id)
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "first_linked_at", "outreach_result", "version", "notes", "is_deleted",
                "deleted_at", "created_at", "updated_at", "influencer_id", "task_id", "tenant_id",
            ),
            out,
        )
        self.source_target_ids = {}
        if not self.report.apply:
            self.source_target_ids = {
                source_id: -index
                for index, source_id in enumerate(source_target_keys, 1)
            }
            return
        for source_id, (task_id, influencer_id) in source_target_keys.items():
            row = self._fetchone(
                self.target,
                f"SELECT id FROM {qident(self.args.target_db)}.influencers_outreachtarget "
                "WHERE tenant_id = %s AND task_id = %s AND influencer_id = %s",
                (self.target_tenant_id, task_id, influencer_id),
            )
            if row:
                self.source_target_ids[source_id] = int(row["id"])

    def _process_fulfillments(self) -> None:
        table = "influencers_samplefulfillment"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        source_keys: dict[int, str] = {}
        for row in rows:
            influencer_id = self.influencer_source_ids.get(int(row["influencer_id"]))
            owner_id = self._source_fk(row["owner_id"], table, "owner_id", True)
            store_id = self._store_fk(row["store_id"], table)
            if influencer_id is None or owner_id is None or store_id is None:
                self.report.skipped(table, "parent:unmapped")
                continue
            task_id = (
                getattr(self, "source_task_ids", {}).get(int(row["outreach_task_id"]))
                if row["outreach_task_id"] is not None
                else None
            )
            if row["outreach_task_id"] is not None and task_id is None:
                self.report.skipped(table, "outreach_task:unmapped")
                continue
            target_id = (
                getattr(self, "source_target_ids", {}).get(int(row["outreach_target_id"]))
                if row["outreach_target_id"] is not None
                else None
            )
            if row["outreach_target_id"] is not None and target_id is None:
                self.report.skipped(table, "outreach_target:unmapped")
                continue
            deleted_by_id = (
                self._source_fk(row["deleted_by_id"], table, "deleted_by_id", False)
                if row["deleted_by_id"] is not None
                else None
            )
            out.append(
                (
                    row["fulfillment_no"], row["request_key"], row["request_hash"], row["status"],
                    row["source"], row["external_id"], row["version"], row["notes"],
                    row["finalized_at"], row["created_at"], row["updated_at"], influencer_id,
                    task_id, owner_id, store_id, self.target_tenant_id, row["external_product_id"],
                    row["product_name_snapshot"], row["sample_order_no"], row["sample_sent_at"],
                    row["shipped_at"], target_id, row["sku_quantity"], row["sales_amount"],
                    row["calculated_cost"], row["pricing_status"], row["priced_at"], row["deleted_at"],
                    deleted_by_id, row["is_deleted"], row["link_type"], row["quick_tags"],
                    row["video_deadline_at"],
                )
            )
            source_keys[int(row["id"])] = str(row["fulfillment_no"])
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "fulfillment_no", "request_key", "request_hash", "status", "source",
                "external_id", "version", "notes", "finalized_at", "created_at", "updated_at",
                "influencer_id", "outreach_task_id", "owner_id", "store_id", "tenant_id",
                "external_product_id", "product_name_snapshot", "sample_order_no", "sample_sent_at",
                "shipped_at", "outreach_target_id", "sku_quantity", "sales_amount",
                "calculated_cost", "pricing_status", "priced_at", "deleted_at", "deleted_by_id",
                "is_deleted", "link_type", "quick_tags", "video_deadline_at",
            ),
            out,
        )
        self.fulfillment_ids = {}
        self.source_fulfillment_ids = {}
        if not self.report.apply:
            self.fulfillment_ids = {
                fulfillment_no: -index
                for index, fulfillment_no in enumerate(dict.fromkeys(source_keys.values()), 1)
            }
            self.source_fulfillment_ids = {
                source_id: self.fulfillment_ids.get(no)
                for source_id, no in source_keys.items()
                if self.fulfillment_ids.get(no)
            }
            return
        if source_keys:
            marks = placeholders(len(source_keys))
            rows2 = self._fetchall(
                self.target,
                f"SELECT id, fulfillment_no FROM {qident(self.args.target_db)}.influencers_samplefulfillment "
                f"WHERE tenant_id = %s AND fulfillment_no IN ({marks})",
                (self.target_tenant_id, *source_keys.values()),
            )
            self.fulfillment_ids = {
                str(row["fulfillment_no"]): int(row["id"]) for row in rows2
            }
            self.source_fulfillment_ids = {
                source_id: self.fulfillment_ids.get(no)
                for source_id, no in source_keys.items()
                if self.fulfillment_ids.get(no)
            }

    def _process_sample_items(self) -> None:
        table = "influencers_sampleitem"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        for row in rows:
            fulfillment_id = getattr(self, "source_fulfillment_ids", {}).get(
                int(row["fulfillment_id"])
            )
            if fulfillment_id is None:
                self.report.skipped(table, "fulfillment:unmapped")
                continue
            sku_id = self._sku_fk(row["requested_sku"], table)
            out.append(
                (
                    row["external_product_id"], row["site_code"], row["requested_sku"],
                    row["product_name"], row["quantity"], row["unit_price"], row["unit_cost"],
                    row["currency"], row["price_match_status"], row["created_at"],
                    row["updated_at"], fulfillment_id, sku_id, self.target_tenant_id,
                    row["normalized_sku"], row["matched_sku_code"], row["matched_legacy_sku_code"],
                    row["sales_amount"], row["cost_amount"], row["cost_match_status"],
                    row["price_source"], row["cost_source"], row["price_snapshot_at"],
                    row["cost_snapshot_at"], row["match_notes"],
                )
            )
        self.report.attempted(table, len(out))
        # requested_sku is nullable and therefore its database UNIQUE key
        # permits repeated NULL rows.  Use the handoff's stable fallback key
        # for legacy rows without a requested SKU.
        if out:
            existing = self._fetchall(
                self.target,
                f"SELECT fulfillment_id, requested_sku, external_product_id, "
                f"site_code, product_name, quantity "
                f"FROM {qident(self.args.target_db)}.{qident(table)} "
                "WHERE tenant_id = %s",
                (self.target_tenant_id,),
            )

            def item_key(item: Sequence[Any]) -> tuple[str, ...]:
                requested = key_for(item[2])
                if requested:
                    return (str(item[11]), "sku", requested)
                return (
                    str(item[11]),
                    "fallback",
                    key_for(item[0]),
                    key_for(item[1]),
                    key_for(item[3]),
                    str(item[4]),
                )

            existing_keys = set()
            for row in existing:
                requested = key_for(row["requested_sku"])
                if requested:
                    existing_keys.add((str(row["fulfillment_id"]), "sku", requested))
                else:
                    existing_keys.add(
                        (
                            str(row["fulfillment_id"]),
                            "fallback",
                            key_for(row["external_product_id"]),
                            key_for(row["site_code"]),
                            key_for(row["product_name"]),
                            str(row["quantity"]),
                        )
                    )
            unique_out = []
            for item in out:
                key = item_key(item)
                if key in existing_keys:
                    self.report.tables[table]["existing_or_unchanged"] += 1
                    continue
                existing_keys.add(key)
                unique_out.append(item)
            out = unique_out
        self._insert(
            table,
            (
                "external_product_id", "site_code", "requested_sku", "product_name", "quantity",
                "unit_price", "unit_cost", "currency", "price_match_status", "created_at",
                "updated_at", "fulfillment_id", "sku_id", "tenant_id", "normalized_sku",
                "matched_sku_code", "matched_legacy_sku_code", "sales_amount", "cost_amount",
                "cost_match_status", "price_source", "cost_source", "price_snapshot_at",
                "cost_snapshot_at", "match_notes",
            ),
            out,
        )

    def _process_fulfillment_events(self) -> None:
        table = "influencers_fulfillmentstatusevent"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        for row in rows:
            fulfillment_id = getattr(self, "source_fulfillment_ids", {}).get(
                int(row["fulfillment_id"])
            )
            actor_id = self._source_fk(row["actor_id"], table, "actor_id", True)
            if fulfillment_id is None or actor_id is None:
                self.report.skipped(table, "parent:unmapped")
                continue
            out.append(
                (
                    row["from_status"], row["to_status"], row["reason"], row["created_at"],
                    actor_id, self.target_tenant_id, fulfillment_id,
                )
            )
        self.report.attempted(table, len(out))
        # Fulfillment history also has only a surrogate primary key.  Use the
        # fulfillment + resulting status + event timestamp natural key so a
        # second run does not append the same history rows.
        if out:
            existing = self._fetchall(
                self.target,
                f"SELECT fulfillment_id, to_status, created_at "
                f"FROM {qident(self.args.target_db)}.{qident(table)} "
                "WHERE tenant_id = %s",
                (self.target_tenant_id,),
            )
            existing_keys = {
                (str(row["fulfillment_id"]), str(row["to_status"]), str(row["created_at"]))
                for row in existing
            }
            unique_out = []
            for item in out:
                key = (str(item[6]), str(item[1]), str(item[3]))
                if key in existing_keys:
                    self.report.tables[table]["existing_or_unchanged"] += 1
                    continue
                existing_keys.add(key)
                unique_out.append(item)
            out = unique_out
        self._insert(
            table,
            (
                "from_status", "to_status", "reason", "created_at",
                "actor_id", "tenant_id", "fulfillment_id",
            ),
            out,
        )

    def _process_import_batches(self) -> None:
        table = "influencers_importbatch"
        rows = list(self._iter_source(table))
        self.report.source(table, len(rows))
        out = []
        source_keys = {}
        for row in rows:
            created_by_id = self._source_fk(row["created_by_id"], table, "created_by_id", True)
            if created_by_id is None:
                continue
            # Prefix the source namespace so a source batch key can never
            # collide with a native target import batch.
            source = f"devb_{row['source']}"
            batch_key = f"v24431:{row['batch_key']}"
            out.append(
                (
                    source, batch_key, row["status"], row["row_count"], row["error_count"],
                    row["created_at"], row["completed_at"], created_by_id, self.target_tenant_id,
                )
            )
            source_keys[str(row["batch_key"])] = (source, batch_key)
        self.report.attempted(table, len(out))
        self._insert(
            table,
            (
                "source", "batch_key", "status", "row_count", "error_count",
                "created_at", "completed_at", "created_by_id", "tenant_id",
            ),
            out,
        )
        self.batch_ids = {}
        for source, batch_key in source_keys.values():
            row = self._fetchone(
                self.target,
                f"SELECT id FROM {qident(self.args.target_db)}.influencers_importbatch "
                "WHERE tenant_id = %s AND source = %s AND batch_key = %s",
                (self.target_tenant_id, source, batch_key),
            )
            if row:
                self.batch_ids[batch_key] = int(row["id"])

    def migrate(self) -> dict[str, Any]:
        self._resolve_tenant()
        self._resolve_users()
        self._resolve_platforms()
        self._resolve_stores()
        self._resolve_spus()
        self._resolve_skus()
        # Influencers are the root of all downstream relations.
        self._resolve_influencers()
        self._process_profiles()
        self._process_contacts()
        self._process_listings()
        self._process_prices()
        self._process_tasks()
        self._process_targets()
        self._process_fulfillments()
        self._process_sample_items()
        self._process_fulfillment_events()
        self._process_import_batches()
        for table in DERIVED_OR_EMPTY_TABLES:
            self.report.add_note(f"{table}: skipped as derived/empty by交接包 policy")
        target_counts = {
            table: self._count_target(table)
            for table in SOURCE_TABLES
            if table != "influencers_influencer"
        }
        target_counts["influencers_influencer"] = self._count_target(
            "influencers_influencer"
        )
        return target_counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-db", required=True)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument("--source-tenant-id", type=int, default=1)
    parser.add_argument("--db-host", default=os.getenv("DB_HOST", "127.0.0.1"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("DB_PORT", "3306")))
    parser.add_argument("--db-user", default=os.getenv("DB_USER", ""))
    parser.add_argument(
        "--db-password",
        default=os.getenv("DB_PASSWORD"),
        help="不建议在命令行传递；优先使用 DB_PASSWORD 环境变量。",
    )
    parser.add_argument(
        "--stage-db-host",
        default=os.getenv("STAGE_DB_HOST"),
        help="staging 专用主机；未提供时回退到 --db-host/DB_HOST。",
    )
    parser.add_argument(
        "--stage-db-port",
        type=int,
        default=(
            int(os.getenv("STAGE_DB_PORT"))
            if os.getenv("STAGE_DB_PORT")
            else None
        ),
        help="staging 专用端口；未提供时回退到 --db-port/DB_PORT。",
    )
    parser.add_argument(
        "--stage-db-user",
        default=os.getenv("STAGE_DB_USER"),
        help="staging 专用账号；未提供时回退到 --db-user/DB_USER。",
    )
    parser.add_argument(
        "--stage-db-password",
        default=os.getenv("STAGE_DB_PASSWORD"),
        help="staging 专用密码；未提供时回退到 --db-password/DB_PASSWORD。",
    )
    parser.add_argument(
        "--target-db-host",
        default=os.getenv("TARGET_DB_HOST"),
        help="正式库专用主机；未提供时回退到 --db-host/DB_HOST。",
    )
    parser.add_argument(
        "--target-db-port",
        type=int,
        default=(
            int(os.getenv("TARGET_DB_PORT"))
            if os.getenv("TARGET_DB_PORT")
            else None
        ),
        help="正式库专用端口；未提供时回退到 --db-port/DB_PORT。",
    )
    parser.add_argument(
        "--target-db-user",
        default=os.getenv("TARGET_DB_USER"),
        help="正式库专用账号；未提供时回退到 --db-user/DB_USER。",
    )
    parser.add_argument(
        "--target-db-password",
        default=os.getenv("TARGET_DB_PASSWORD"),
        help="正式库专用密码；未提供时回退到 --db-password/DB_PASSWORD。",
    )
    parser.add_argument("--user-map-file")
    parser.add_argument("--store-map-file")
    parser.add_argument("--platform-map-file")
    parser.add_argument("--spu-map-file")
    parser.add_argument("--derive-store-map", action="store_true")
    parser.add_argument("--target-admin-username")
    parser.add_argument(
        "--source-admin-ids",
        default="",
        help="仅将逗号分隔的、经人工确认的源账号ID映射到目标超级管理员用户名。",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--report")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行正式租户写入；不指定时始终为只读 dry-run。",
    )
    parser.add_argument(
        "--confirm-tenant-code",
        help="执行 --apply 时必须与 --tenant-code 完全一致，防止误写租户。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 2000:
        raise SystemExit("--batch-size 必须在1到2000之间")
    for role in ("stage", "target"):
        credentials = effective_db_credentials(args, role)
        if not credentials["user"] or credentials["password"] is None:
            raise SystemExit(
                f"必须提供 {role} 数据库账号和密码；可用 "
                f"--{role}-db-user/--{role}-db-password，或通用 DB_USER/DB_PASSWORD"
            )
    if args.apply and args.confirm_tenant_code != args.tenant_code:
        raise SystemExit("正式写入必须提供匹配的 --confirm-tenant-code")
    args.source_admin_ids = {
        item.strip()
        for item in args.source_admin_ids.split(",")
        if item.strip()
    }
    user_map = read_map_file(args.user_map_file, "source_id", "target_username")
    store_map = read_map_file(args.store_map_file, "source_store_id", "target_store_code")
    platform_map = read_map_file(
        args.platform_map_file,
        "source_platform_code",
        "target_platform_code",
    )
    spu_map = read_map_file(args.spu_map_file, "source_spu_id", "target_spu_code")
    reporter = Reporter(args.apply, args.report)
    source = db_connect(args, args.stage_db, readonly=True, role="stage")
    target = db_connect(
        args,
        args.target_db,
        readonly=not args.apply,
        role="target",
    )
    try:
        migrator = Migrator(
            args,
            source,
            target,
            reporter,
            user_map,
            store_map,
            platform_map,
            spu_map,
        )
        target_counts = migrator.migrate()
        payload = reporter.finish(args, target_counts)
        print(
            json.dumps(
                {
                    "mode": payload["mode"],
                    "target_tenant_code": args.tenant_code,
                    "tables": payload["tables"],
                    "issue_categories": {
                        key: value["count"] for key, value in payload["issues"].items()
                    },
                    "report": args.report or "(stdout only)",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
