# -*- coding: utf-8 -*-
"""从 店铺配置.ini 读取各店导出标签（Excel/Z 盘文件名前缀）。"""
from __future__ import annotations

import configparser
import json
import re
from pathlib import Path

from common.paths import DEFAULT_SHOP_HUB, PROJECT_ROOT, SHOP_CONFIG_INI


def _read_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    return cp


def _registry_sections(cp: configparser.ConfigParser) -> list[str]:
    skip = {"应用", "目录", "默认店", "批量启用", "导出文件名", "站点", "平台"}
    return [s for s in cp.sections() if s not in skip]


def load_export_tags(ini_path: Path | None = None) -> dict[str, str]:
    """返回 {店键: 导出标签}。"""
    path = ini_path or SHOP_CONFIG_INI
    if not path.exists():
        return {}
    cp = _read_ini(path)
    out: dict[str, str] = {}
    for key in _registry_sections(cp):
        tag = cp.get(key, "导出标签", fallback="").strip()
        if tag:
            out[key.upper()] = tag
    return out


def load_filename_stems(ini_path: Path | None = None) -> dict[str, str]:
    """导出 Excel 文件名中间段，如 产品数据表 / 商品sku信息。"""
    from common.excel_names import DEFAULT_ANALYTICS_STEMS, DEFAULT_FINANCE_STEMS

    defaults = {
        **DEFAULT_ANALYTICS_STEMS,
        "order": "订单数据表",
        **DEFAULT_FINANCE_STEMS,
    }
    path = ini_path or SHOP_CONFIG_INI
    if not path.exists():
        return defaults
    cp = _read_ini(path)
    if not cp.has_section("导出文件名"):
        return defaults
    sec = cp["导出文件名"]
    mapping = {
        "product": sec.get("产品表", fallback=defaults["product"]).strip() or defaults["product"],
        "sku": sec.get("SKU表", fallback=defaults["sku"]).strip() or defaults["sku"],
        "video": sec.get("视频表", fallback=defaults["video"]).strip() or defaults["video"],
        "shop": sec.get("店铺表", fallback=defaults["shop"]).strip() or defaults["shop"],
        "order": sec.get("订单表", fallback=defaults["order"]).strip() or defaults["order"],
        "statements": sec.get("结算单", fallback=defaults["statements"]).strip() or defaults["statements"],
        "statement_tx": sec.get("结算明细", fallback=defaults["statement_tx"]).strip() or defaults["statement_tx"],
        "payments": sec.get("付款", fallback=defaults["payments"]).strip() or defaults["payments"],
        "withdrawals": sec.get("提现", fallback=defaults["withdrawals"]).strip() or defaults["withdrawals"],
        "unsettled": sec.get("未结算", fallback=defaults["unsettled"]).strip() or defaults["unsettled"],
    }
    return mapping


def merge_shop_tags(shops: list[dict], ini_path: Path | None = None) -> list[dict]:
    tags = load_export_tags(ini_path)
    if not tags:
        return shops
    out: list[dict] = []
    for s in shops:
        item = dict(s)
        key = item.get("key", "").upper()
        if key in tags:
            item["export_tag"] = tags[key]
        out.append(item)
    return out


def sync_export_tag_to_env(hub_dir: Path, shop_key: str, export_tag: str) -> None:
    """把 店铺配置.ini 的导出标签写入 config_<店键>.env 和 shops.json。"""
    if not export_tag:
        return
    hub = Path(hub_dir)
    env_path = hub / f"config_{shop_key.upper()}.env"
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        if re.search(r"^TTS_EXPORT_SHOP_TAG=", text, flags=re.M):
            text = re.sub(
                r"^TTS_EXPORT_SHOP_TAG=.*$",
                f"TTS_EXPORT_SHOP_TAG={export_tag}",
                text,
                flags=re.M,
            )
        else:
            text = text.rstrip() + f"\nTTS_EXPORT_SHOP_TAG={export_tag}\n"
        env_path.write_text(text, encoding="utf-8")

    manifest = hub / "shops.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for s in data.get("shops", []):
            if s.get("key", "").upper() == shop_key.upper():
                s["export_tag"] = export_tag
                break
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync_all_export_tags(hub_dir: Path | None = None, ini_path: Path | None = None) -> None:
    hub = Path(hub_dir or DEFAULT_SHOP_HUB)
    for key, tag in load_export_tags(ini_path).items():
        sync_export_tag_to_env(hub, key, tag)
