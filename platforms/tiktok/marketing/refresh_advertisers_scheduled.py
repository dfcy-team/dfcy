# -*- coding: utf-8 -*-
"""定时刷新各店铺 TikTok 广告户列表（无需重新 OAuth）。"""
from __future__ import annotations

import argparse
import configparser
import sys
from datetime import datetime
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from common.paths import CONFIG_DIR  # noqa: E402

DEFAULT_INI = CONFIG_DIR / "广告定时刷新.ini"


def _read_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    return cp


def _log_dir(ini_path: Path) -> Path:
    cp = _read_ini(ini_path)
    rel = cp.get("定时", "日志目录", fallback="logs/ads_refresh").strip() or "logs/ads_refresh"
    d = Path(rel)
    if not d.is_absolute():
        d = PROJECT_ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_refresh(*, ini_path: Path | None = None) -> int:
    from oauth import refresh_all_shop_advertisers

    ini = ini_path or DEFAULT_INI
    log_root = _log_dir(ini)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_root / f"refresh_{ts}.log"

    lines: list[str] = []
    lines.append(f"[{datetime.now().isoformat(timespec='seconds')}] 开始刷新广告户")

    results = refresh_all_shop_advertisers()
    if not results:
        lines.append("无已授权店铺，跳过")
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0

    ok_n = 0
    for r in results:
        label = r.get("shop_label", "")
        if r.get("ok"):
            ok_n += 1
            lines.append(
                f"  OK {label}: {r.get('advertiser_count', 0)} 户, "
                f"默认={r.get('default_advertiser_id', '')}"
            )
        else:
            lines.append(f"  FAIL {label}: {r.get('error', '')}")

    lines.append(f"完成 {ok_n}/{len(results)} 家店铺")
    text = "\n".join(lines) + "\n"
    log_file.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if ok_n == len(results) else 1


def main() -> int:
    p = argparse.ArgumentParser(description="刷新全部已授权店铺的广告户列表")
    p.add_argument("--config", default=str(DEFAULT_INI), help="定时配置 ini")
    args = p.parse_args()
    return run_refresh(ini_path=Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
