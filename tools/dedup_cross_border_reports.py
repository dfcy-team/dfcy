# -*- coding: utf-8 -*-
"""
一键清除跨境店重复报表行。

问题：同一 shop_id 的 PH/TH/MY 多国 env 各跑一遍，同一 product_id+日期 写入多行。
策略：每个 shop_id 组只保留「主配置店」行，删除同组其他国家配置的重复行。

用法:
  python tools/dedup_cross_border_reports.py --dry-run
  python tools/dedup_cross_border_reports.py --execute
  python tools/dedup_cross_border_reports.py --execute --start 2026-03-05 --end 2026-07-05
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.cross_border_shop import cross_border_duplicate_groups, load_run_shop_keys
from common.db_config import load_db_config

DEFAULT_START = "2026-03-05"
DEFAULT_END = "2026-07-05"

TABLE_SPECS = (
    ("product_table", "product_id"),
    ("sku_table", "sku_id"),
    ("affiliate_table", "product_id"),
)


def _load_table_names(cfg: dict) -> list[tuple[str, str]]:
    tables: list[tuple[str, str]] = []
    for cfg_key, entity_col in TABLE_SPECS:
        name = cfg.get(cfg_key, "").strip()
        if name:
            tables.append((name, entity_col))
    return tables


def _count_duplicates(
    cur,
    table: str,
    entity_col: str,
    primary: str,
    secondary: list[str],
    start: str,
    end: str,
) -> int:
    if not secondary:
        return 0
    placeholders = ", ".join(["%s"] * len(secondary))
    sql = f"""
        SELECT COUNT(*) FROM `{table}` t
        WHERE t.shop_abbr IN ({placeholders})
          AND t.data_time BETWEEN %s AND %s
          AND EXISTS (
            SELECT 1 FROM `{table}` p
            WHERE p.data_time = t.data_time
              AND p.`{entity_col}` = t.`{entity_col}`
              AND p.shop_abbr = %s
          )
    """
    params = [*secondary, start, end, primary]
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0] if row else 0)


def _delete_duplicates(
    cur,
    table: str,
    entity_col: str,
    primary: str,
    secondary: list[str],
    start: str,
    end: str,
) -> int:
    if not secondary:
        return 0
    placeholders = ", ".join(["%s"] * len(secondary))
    sql = f"""
        DELETE t FROM `{table}` t
        INNER JOIN `{table}` p
          ON p.data_time = t.data_time
         AND p.`{entity_col}` = t.`{entity_col}`
         AND p.shop_abbr = %s
        WHERE t.shop_abbr IN ({placeholders})
          AND t.data_time BETWEEN %s AND %s
    """
    params = [primary, *secondary, start, end]
    cur.execute(sql, params)
    return cur.rowcount


def _default_db_ini() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "config" / "db.ini",
        Path(r"C:\Users\Administrator\Desktop\每日数据导入数据库\db.ini"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="清除跨境店 product_id/sku_id 重复报表行")
    ap.add_argument("--execute", action="store_true", help="实际删除（默认仅预览）")
    ap.add_argument("--dry-run", action="store_true", help="仅统计将删除的行数")
    ap.add_argument("--start", default=DEFAULT_START, help=f"开始日期，默认 {DEFAULT_START}")
    ap.add_argument("--end", default=DEFAULT_END, help=f"结束日期，默认 {DEFAULT_END}")
    ap.add_argument("--db-ini", default="", help="db.ini 路径，默认自动查找")
    args = ap.parse_args()

    dry_run = not args.execute or args.dry_run
    if args.execute and not args.dry_run:
        dry_run = False

    ini = Path(args.db_ini) if args.db_ini else _default_db_ini()
    try:
        cfg = load_db_config(ini)
    except FileNotFoundError as exc:
        print(f"错误: {exc}")
        print("请指定 --db-ini，或放置 config/db.ini / 每日数据导入数据库\\db.ini")
        return 1

    tables = _load_table_names(cfg)
    if not tables:
        print("错误: db.ini [表名] 未配置任何表")
        return 1

    groups = cross_border_duplicate_groups()
    if not groups:
        print("未发现多国共用 shop_id 的跨境组，无需去重。")
        return 0

    run_keys = load_run_shop_keys()
    print("=" * 60)
    print("跨境重复清理" + (" [预览]" if dry_run else " [执行删除]"))
    print(f"日期范围: {args.start} ~ {args.end}")
    print(f"运行店铺.ini 主配置参考: {', '.join(sorted(run_keys)) or '(未配置)'}")
    print("=" * 60)

    try:
        import pymysql
    except ImportError:
        print("请先安装: pip install pymysql")
        return 1

    conn = pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset=cfg["charset"],
    )

    total_would_delete = 0
    total_deleted = 0

    try:
        with conn.cursor() as cur:
            for g in groups:
                primary = str(g["primary"])
                secondary = list(g["secondary"])
                shop_id = g["shop_id"]
                keys = g["shop_keys"]
                print(f"\nshop_id={shop_id}")
                print(f"  组内店: {', '.join(keys)}")
                print(f"  保留主配置: {primary}")
                print(f"  将清理: {', '.join(secondary) or '(无)'}")

                for table, entity_col in tables:
                    try:
                        n = _count_duplicates(
                            cur, table, entity_col, primary, secondary,
                            args.start, args.end,
                        )
                    except pymysql.Error as exc:
                        print(f"  [{table}] 跳过: {exc}")
                        continue

                    if n == 0:
                        print(f"  [{table}] 0 行重复")
                        continue

                    print(f"  [{table}] {'将删除' if dry_run else '删除'} {n} 行 (按 {entity_col})")
                    total_would_delete += n

                    if not dry_run:
                        deleted = _delete_duplicates(
                            cur, table, entity_col, primary, secondary,
                            args.start, args.end,
                        )
                        total_deleted += deleted

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    print("\n" + "=" * 60)
    if dry_run:
        print(f"预览合计将删除: {total_would_delete} 行")
        print("确认后执行: python tools/dedup_cross_border_reports.py --execute")
    else:
        print(f"已删除: {total_deleted} 行")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
