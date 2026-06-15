# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "test_env"))

from product_api import get_category_attributes, get_product, setup_client

c, t, cp, _ = setup_client(["--shop", "TK6PH"])
attrs = get_category_attributes(c, t, cp, "810376")
tpl = json.loads((SCRIPT_DIR / "create_attrs.json").read_text(encoding="utf-8"))
tpl_ids = {a["id"] for a in tpl}

print("=== category 810376 attributes ===")
for a in attrs:
    aid = str(a.get("id"))
    req = a.get("is_required") or a.get("required")
    mark = " *REQUIRED*" if req else ""
    in_tpl = "OK" if aid in tpl_ids else "MISSING"
    print(f"{aid} {a.get('name')}{mark} [{in_tpl}]")

p = get_product(c, t, cp, "1734369244110423722")
pa = p.get("product_attributes") or []
print("\n=== reference product attributes ===")
for a in pa:
    vals = ",".join(v.get("name", "") for v in (a.get("values") or []))
    print(f"{a.get('id')} {a.get('name')} = {vals}")

ref_ids = {str(a.get("id")) for a in pa}
missing = ref_ids - tpl_ids
if missing:
    print("\n=== in reference but NOT in create_attrs.json ===")
    for a in pa:
        if str(a.get("id")) in missing:
            print(f"  {a.get('id')} {a.get('name')}")

img = SCRIPT_DIR / "samples" / "main.jpg"
print(f"\nmain.jpg exists: {img.is_file()} -> {img}")
