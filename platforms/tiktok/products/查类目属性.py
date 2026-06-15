# -*- coding: utf-8 -*-
"""GET /categories/{id}/attributes — 导出类目属性模板 JSON。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from product_api import (
    attributes_template_from_api,
    get_category_attributes,
    ini_get,
    load_ini,
    recommend_category,
    save_json,
    setup_client,
)


def main() -> int:
    cp = load_ini()
    ap = argparse.ArgumentParser(description="查询类目属性并生成 create_attrs 模板")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--category-id", default=ini_get(cp, "create", "category_id", ""))
    ap.add_argument("--title", default=ini_get(cp, "create", "title", ""), help="用于推荐类目")
    ap.add_argument("--write-template", action="store_true", help="写入 create_attrs.json")
    args = ap.parse_args()

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")

    category_id = args.category_id
    if not category_id and args.title:
        rr = recommend_category(client, token, cipher, args.title)
        if rr.get("code") == 0:
            leaf = (rr.get("data") or {}).get("leaf_category_id") or ""
            if leaf:
                category_id = str(leaf)
                print(f"推荐类目: {category_id}")
        else:
            print(f"推荐类目失败: {rr.get('message')}")

    if not category_id:
        print("请填写 --category-id 或 ini [create] category_id / title")
        return 1

    attrs = get_category_attributes(client, token, cipher, category_id)
    print(f"\n类目 {category_id} 共 {len(attrs)} 个属性:\n")
    for a in attrs:
        vals = a.get("values") or []
        print(f"  {a.get('id')}  {a.get('name')}  可选值={len(vals)}")

    template = attributes_template_from_api(attrs)
    out_name = f"category_{category_id}_attrs.json"
    save_json(out_name, {"category_id": category_id, "product_attributes": template})
    print(f"\n已保存模板: logs/{out_name}")

    tpl_path = Path(__file__).resolve().parent / "create_attrs.json"
    if args.write_template or not tpl_path.exists():
        tpl_path.write_text(
            __import__("json").dumps(template, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已写入可编辑文件: {tpl_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
