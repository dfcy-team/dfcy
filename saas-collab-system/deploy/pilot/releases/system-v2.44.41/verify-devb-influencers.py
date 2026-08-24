#!/usr/bin/env python3
"""Read-only post-import checks for the developer-B influencer migration.

The verifier never mutates either database.  It resolves the target tenant by
``tenants_tenant.code`` and reports only tenant-scoped counts, duplicate
natural keys, and foreign-key/tenant-boundary violations.  A non-zero exit
status means that at least one integrity check failed.

Use ``--stage-db`` when source/staging counts should be included.  The stage
and target connections can use separate role-specific CLI options or
``STAGE_DB_*``/``TARGET_DB_*`` environment variables; generic ``DB_*`` values
remain the fallback for backwards compatibility.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence


IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def qident(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise SystemExit(f"invalid database identifier: {value!r}")
    return f"`{value}`"


def placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


def load_driver():
    try:
        import MySQLdb  # type: ignore

        return MySQLdb
    except ImportError:
        try:
            import pymysql  # type: ignore

            return pymysql
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit("需要 mysqlclient 或 PyMySQL 才能运行只读验收") from exc


def effective_db_credentials(args: argparse.Namespace, role: str) -> dict[str, Any]:
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


def connect(args: argparse.Namespace, database: str, role: str = "target"):
    driver = load_driver()
    credentials = effective_db_credentials(args, role)
    kwargs = {
        "host": credentials["host"],
        "port": credentials["port"],
        "user": credentials["user"],
        "passwd": credentials["password"],
        "db": database,
        "charset": "utf8mb4",
    }
    if driver.__name__ == "pymysql":
        kwargs["password"] = kwargs.pop("passwd")
    conn = driver.connect(**kwargs)
    # Keep this connection read-only at the transaction level as an
    # additional guard.  The script itself contains no DML.
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def fetchall(conn, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [item[0] for item in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def scalar(conn, sql: str, params: Sequence[Any] = ()) -> int:
    rows = fetchall(conn, sql, params)
    return int(next(iter(rows[0].values()))) if rows else 0


def tenant_id(conn, database: str, code: str) -> int:
    rows = fetchall(
        conn,
        f"SELECT id FROM {qident(database)}.tenants_tenant WHERE code = %s",
        (code,),
    )
    if len(rows) != 1:
        raise SystemExit(f"target tenant code={code!r} did not resolve uniquely")
    return int(rows[0]["id"])


def table_counts(conn, database: str, tenant: int) -> dict[str, int]:
    tables = (
        "influencers_influencer",
        "influencers_influencerprofile",
        "influencers_influencercontact",
        "influencers_influencerrestriction",
        "influencers_influencerrestrictevent",
        "influencers_storeproductlisting",
        "influencers_skupricesnapshot",
        "influencers_outreachtask",
        "influencers_outreachtarget",
        "influencers_samplefulfillment",
        "influencers_sampleitem",
        "influencers_fulfillmentstatusevent",
        "influencers_importbatch",
    )
    return {
        table: scalar(
            conn,
            f"SELECT COUNT(*) AS n FROM {qident(database)}.{qident(table)} WHERE tenant_id = %s",
            (tenant,),
        )
        for table in tables
    }


def duplicate_checks(conn, database: str, tenant: int) -> dict[str, int]:
    checks = {
        "influencer_code": """
            SELECT COUNT(*) FROM (
                SELECT code FROM {db}.influencers_influencer
                WHERE tenant_id = %s GROUP BY code HAVING COUNT(*) > 1
            ) d
        """,
        "task_no": """
            SELECT COUNT(*) FROM (
                SELECT task_no FROM {db}.influencers_outreachtask
                WHERE tenant_id = %s GROUP BY task_no HAVING COUNT(*) > 1
            ) d
        """,
        "fulfillment_no": """
            SELECT COUNT(*) FROM (
                SELECT fulfillment_no FROM {db}.influencers_samplefulfillment
                WHERE tenant_id = %s GROUP BY fulfillment_no HAVING COUNT(*) > 1
            ) d
        """,
        "listing_natural_key": """
            SELECT COUNT(*) FROM (
                SELECT store_id, site_code, external_product_id
                FROM {db}.influencers_storeproductlisting
                WHERE tenant_id = %s
                GROUP BY store_id, site_code, external_product_id HAVING COUNT(*) > 1
            ) d
        """,
        "sku_snapshot_natural_key": """
            SELECT COUNT(*) FROM (
                SELECT listing_id, external_sku, variant_id
                FROM {db}.influencers_skupricesnapshot
                WHERE tenant_id = %s
                GROUP BY listing_id, external_sku, variant_id HAVING COUNT(*) > 1
            ) d
        """,
        "target_relation": """
            SELECT COUNT(*) FROM (
                SELECT task_id, influencer_id
                FROM {db}.influencers_outreachtarget
                WHERE tenant_id = %s
                GROUP BY task_id, influencer_id HAVING COUNT(*) > 1
            ) d
        """,
        "sample_item_requested_sku": """
            SELECT COUNT(*) FROM (
                SELECT fulfillment_id, requested_sku
                FROM {db}.influencers_sampleitem
                WHERE tenant_id = %s
                GROUP BY fulfillment_id, requested_sku HAVING COUNT(*) > 1
            ) d
        """,
        "restriction_event_natural_key": """
            SELECT COUNT(*) FROM (
                SELECT influencer_id, action, occurred_at
                FROM {db}.influencers_influencerrestrictevent
                WHERE tenant_id = %s
                GROUP BY influencer_id, action, occurred_at HAVING COUNT(*) > 1
            ) d
        """,
        "fulfillment_event_natural_key": """
            SELECT COUNT(*) FROM (
                SELECT fulfillment_id, to_status, created_at
                FROM {db}.influencers_fulfillmentstatusevent
                WHERE tenant_id = %s
                GROUP BY fulfillment_id, to_status, created_at HAVING COUNT(*) > 1
            ) d
        """,
    }
    return {
        name: scalar(conn, sql.format(db=qident(database)), (tenant,))
        for name, sql in checks.items()
    }


def orphan_checks(conn, database: str, tenant: int) -> dict[str, int]:
    db = qident(database)
    checks = {
        "profile_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_influencerprofile p
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = p.influencer_id AND i.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND i.id IS NULL
        """,
        "contact_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_influencercontact c
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = c.influencer_id AND i.tenant_id = c.tenant_id
            WHERE c.tenant_id = %s AND i.id IS NULL
        """,
        "restriction_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_influencerrestriction r
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = r.influencer_id AND i.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND i.id IS NULL
        """,
        "restriction_event_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_influencerrestrictevent e
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = e.influencer_id AND i.tenant_id = e.tenant_id
            WHERE e.tenant_id = %s AND i.id IS NULL
        """,
        "listing_store": f"""
            SELECT COUNT(*) FROM {db}.influencers_storeproductlisting l
            LEFT JOIN {db}.masterdata_storemaster s
              ON s.id = l.store_id AND s.tenant_id = l.tenant_id
            WHERE l.tenant_id = %s AND s.id IS NULL
        """,
        "listing_spu_cross_tenant": f"""
            SELECT COUNT(*) FROM {db}.influencers_storeproductlisting l
            JOIN {db}.products_productspu p ON p.id = l.spu_id
            WHERE l.tenant_id = %s AND l.spu_id IS NOT NULL AND p.tenant_id <> l.tenant_id
        """,
        "price_listing": f"""
            SELECT COUNT(*) FROM {db}.influencers_skupricesnapshot p
            LEFT JOIN {db}.influencers_storeproductlisting l
              ON l.id = p.listing_id AND l.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND l.id IS NULL
        """,
        "price_sku_cross_tenant": f"""
            SELECT COUNT(*) FROM {db}.influencers_skupricesnapshot p
            JOIN {db}.products_productsku s ON s.id = p.sku_id
            WHERE p.tenant_id = %s AND p.sku_id IS NOT NULL AND s.tenant_id <> p.tenant_id
        """,
        "target_task": f"""
            SELECT COUNT(*) FROM {db}.influencers_outreachtarget x
            LEFT JOIN {db}.influencers_outreachtask t
              ON t.id = x.task_id AND t.tenant_id = x.tenant_id
            WHERE x.tenant_id = %s AND t.id IS NULL
        """,
        "target_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_outreachtarget x
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = x.influencer_id AND i.tenant_id = x.tenant_id
            WHERE x.tenant_id = %s AND i.id IS NULL
        """,
        "task_store": f"""
            SELECT COUNT(*) FROM {db}.influencers_outreachtask t
            LEFT JOIN {db}.masterdata_storemaster s
              ON s.id = t.store_id AND s.tenant_id = t.tenant_id
            WHERE t.tenant_id = %s AND s.id IS NULL
        """,
        "task_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_outreachtask t
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = t.influencer_id AND i.tenant_id = t.tenant_id
            WHERE t.tenant_id = %s AND t.influencer_id IS NOT NULL AND i.id IS NULL
        """,
        "fulfillment_influencer": f"""
            SELECT COUNT(*) FROM {db}.influencers_samplefulfillment f
            LEFT JOIN {db}.influencers_influencer i
              ON i.id = f.influencer_id AND i.tenant_id = f.tenant_id
            WHERE f.tenant_id = %s AND i.id IS NULL
        """,
        "fulfillment_store": f"""
            SELECT COUNT(*) FROM {db}.influencers_samplefulfillment f
            LEFT JOIN {db}.masterdata_storemaster s
              ON s.id = f.store_id AND s.tenant_id = f.tenant_id
            WHERE f.tenant_id = %s AND s.id IS NULL
        """,
        "fulfillment_task": f"""
            SELECT COUNT(*) FROM {db}.influencers_samplefulfillment f
            LEFT JOIN {db}.influencers_outreachtask t
              ON t.id = f.outreach_task_id AND t.tenant_id = f.tenant_id
            WHERE f.tenant_id = %s AND f.outreach_task_id IS NOT NULL AND t.id IS NULL
        """,
        "fulfillment_target": f"""
            SELECT COUNT(*) FROM {db}.influencers_samplefulfillment f
            LEFT JOIN {db}.influencers_outreachtarget x
              ON x.id = f.outreach_target_id AND x.tenant_id = f.tenant_id
            WHERE f.tenant_id = %s AND f.outreach_target_id IS NOT NULL AND x.id IS NULL
        """,
        "sample_item_fulfillment": f"""
            SELECT COUNT(*) FROM {db}.influencers_sampleitem s
            LEFT JOIN {db}.influencers_samplefulfillment f
              ON f.id = s.fulfillment_id AND f.tenant_id = s.tenant_id
            WHERE s.tenant_id = %s AND f.id IS NULL
        """,
        "fulfillment_event_parent": f"""
            SELECT COUNT(*) FROM {db}.influencers_fulfillmentstatusevent e
            LEFT JOIN {db}.influencers_samplefulfillment f
              ON f.id = e.fulfillment_id AND f.tenant_id = e.tenant_id
            WHERE e.tenant_id = %s AND f.id IS NULL
        """,
    }
    return {name: scalar(conn, sql, (tenant,)) for name, sql in checks.items()}


def baseline_task_check(conn, database: str, tenant: int, task_nos: Sequence[str]) -> dict[str, Any]:
    if not task_nos:
        return {"requested": [], "missing": []}
    db = qident(database)
    rows = fetchall(
        conn,
        f"SELECT task_no FROM {db}.influencers_outreachtask "
        f"WHERE tenant_id = %s AND task_no IN ({placeholders(len(task_nos))})",
        (tenant, *task_nos),
    )
    found = {str(row["task_no"]) for row in rows}
    return {"requested": list(task_nos), "missing": [item for item in task_nos if item not in found]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument(
        "--stage-db",
        help="可选 staging 库；提供后同时输出源租户行数（只读）。",
    )
    parser.add_argument("--source-tenant-id", type=int, default=1)
    parser.add_argument("--db-host", default=os.getenv("DB_HOST", "127.0.0.1"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("DB_PORT", "3306")))
    parser.add_argument("--db-user", default=os.getenv("DB_USER", ""))
    parser.add_argument("--db-password", default=os.getenv("DB_PASSWORD"))
    parser.add_argument("--stage-db-host", default=os.getenv("STAGE_DB_HOST"))
    parser.add_argument(
        "--stage-db-port",
        type=int,
        default=int(os.getenv("STAGE_DB_PORT")) if os.getenv("STAGE_DB_PORT") else None,
    )
    parser.add_argument("--stage-db-user", default=os.getenv("STAGE_DB_USER"))
    parser.add_argument("--stage-db-password", default=os.getenv("STAGE_DB_PASSWORD"))
    parser.add_argument("--target-db-host", default=os.getenv("TARGET_DB_HOST"))
    parser.add_argument(
        "--target-db-port",
        type=int,
        default=int(os.getenv("TARGET_DB_PORT")) if os.getenv("TARGET_DB_PORT") else None,
    )
    parser.add_argument("--target-db-user", default=os.getenv("TARGET_DB_USER"))
    parser.add_argument("--target-db-password", default=os.getenv("TARGET_DB_PASSWORD"))
    parser.add_argument("--baseline-task-no", action="append", default=[])
    parser.add_argument("--report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for role in ("target", "stage") if args.stage_db else ("target",):
        credentials = effective_db_credentials(args, role)
        if not credentials["user"] or credentials["password"] is None:
            raise SystemExit(
                f"必须提供 {role} 数据库账号和密码；可用 "
                f"--{role}-db-user/--{role}-db-password，或通用 DB_USER/DB_PASSWORD"
            )
    conn = connect(args, args.target_db, role="target")
    stage_conn = connect(args, args.stage_db, role="stage") if args.stage_db else None
    try:
        target_tenant = tenant_id(conn, args.target_db, args.tenant_code)
        counts = table_counts(conn, args.target_db, target_tenant)
        duplicates = duplicate_checks(conn, args.target_db, target_tenant)
        orphans = orphan_checks(conn, args.target_db, target_tenant)
        baseline = baseline_task_check(conn, args.target_db, target_tenant, args.baseline_task_no)
        stage_counts = (
            table_counts(stage_conn, args.stage_db, args.source_tenant_id)
            if stage_conn is not None
            else None
        )
        failed = {
            **{f"duplicate:{key}": value for key, value in duplicates.items() if value},
            **{f"orphan:{key}": value for key, value in orphans.items() if value},
            **({"baseline:missing_task": len(baseline["missing"])} if baseline["missing"] else {}),
        }
        payload = {
            "mode": "read_only",
            "target_db": args.target_db,
            "target_tenant_code": args.tenant_code,
            "target_tenant_id": target_tenant,
            "counts": counts,
            "stage_db": args.stage_db,
            "stage_source_tenant_id": args.source_tenant_id if args.stage_db else None,
            "stage_counts": stage_counts,
            "duplicate_checks": duplicates,
            "orphan_checks": orphans,
            "baseline_tasks": baseline,
            "status": "FAIL" if failed else "PASS",
            "failures": failed,
        }
        output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        print(output, end="")
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(output, encoding="utf-8")
        return 1 if failed else 0
    finally:
        conn.close()
        if stage_conn is not None:
            stage_conn.close()


if __name__ == "__main__":
    sys.exit(main())
