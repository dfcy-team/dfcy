"""Deterministic, data-only PNG renderer for the daily sales ranking."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


WIDTH = 960
MAX_IMAGE_HEIGHT = 16000
BG = "#101827"
INK = "#F4F7FB"
MUTED = "#AAB8CC"
BLUE = "#8AB4FF"
GREEN = "#65D6A4"
RED = "#FF7D89"


def _font(size, bold=False):
    # Debian images install Noto CJK in Dockerfile. Local development can use
    # the packaged label font; missing fonts fail visibly and trigger fallback.
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        str(Path(__file__).parents[1] / "packing/assets/fonts/sc-f2-label-font-v1" / ("SCF2LabelSans-Bold.ttf" if bold else "SCF2LabelSans-Regular.ttf")),
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
    ]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise RuntimeError("No usable CJK font available for sales ranking image")


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _fmt(value, suffix=""):
    n = _num(value)
    return "" if n is None else f"{n:,.2f}{suffix}"


def _missing_roi(row):
    reason = str(row.get("ad_reason") or "")
    if '权限' in reason:
        return '无广告权限'
    if '为 0' in reason or '为0' in reason:
        return '广告费为零'
    if '暂不可用' in reason:
        return '暂不可算'
    return "缺广告费" if "广告" in reason or not reason else "暂不可算"


def _fit_font(draw, value, max_width, preferred=24, minimum=14):
    for size in range(preferred, minimum - 1, -1):
        font = _font(size)
        if draw.textlength(value, font=font) <= max_width:
            return font
    return _font(minimum)


def render_sales_ranking_png(report):
    """Render yesterday's real, scoped observations; today's panel is explicit."""
    data = report["operations"]
    current = data.get('period') == 'current'
    filters = data.get("filters", {})
    groups = defaultdict(list)
    for row in data.get("rows", []):
        groups[str(row.get("currency") or "币种未设置")].append(row)
    for total in data.get("currency_groups", []):
        groups.setdefault(str(total.get("currency") or "币种未设置"), [])
    for rows in groups.values():
        rows.sort(key=lambda row: (_num(row.get("sales_amount")) is None, -(_num(row.get("sales_amount")) or Decimal(0))))

    height = 340 + sum(185 + 82 * len(rows) for rows in groups.values())
    if height > MAX_IMAGE_HEIGHT:
        # Keep all totals or let delivery use its explicit text fallback; never
        # silently truncate currencies or allocate an unbounded bitmap.
        raise ValueError("Sales ranking image exceeds the safe pixel budget")
    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)
    f_title, f_sub, f_head, f_body, f_small = (_font(size, bold) for size, bold in [(36, True), (24, False), (28, True), (24, False), (20, False)])
    draw.rounded_rectangle((24, 24, WIDTH - 24, height - 24), radius=24, fill="#1B2638")
    draw.text((54, 50), "今日累计 · 店铺排行榜" if current else "销售店铺排行榜", font=f_title, fill=INK)
    report_date = str(filters.get("date_from", "日期未知"))
    if current:
        captured = datetime.fromisoformat(data['generated_at'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        draw.text((56, 112), f"截至 {captured}（北京）", font=f_sub, fill=MUTED)
        draw.text((56, 151), "各店当地零点起累计 · 缺历史同点基准，不与昨日全天比较", font=f_small, fill=MUTED)
    else:
        draw.text((56, 112), f"全天  {report_date}   ·   门店当地业务日期", font=f_sub, fill=MUTED)
        draw.text((56, 151), "已结束日期 · 按当前已入库数据生成", font=f_small, fill=MUTED)

    y = 195
    for currency, rows in groups.items():
        draw.rounded_rectangle((48, y, WIDTH - 48, y + 82), radius=12, fill="#26364D")
        total = next((item for item in data.get("currency_groups", []) if str(item.get("currency") or "币种未设置") == currency), {})
        total_gmv = _fmt(total.get("sales_amount")) or "数据不完整"
        total_roi = _fmt(total.get("roi"), " 倍") or _missing_roi(total)
        draw.text((68, y + 8), f"{currency}  ·  授权范围合计", font=f_small, fill=BLUE)
        draw.text((68, y + 43), f"GMV {total_gmv} {currency}   ·   ROI {total_roi}", font=f_small, fill=INK)
        y += 94
        columns = [(58, "排名"), (124, "店铺 / 国家"), (438, f"GMV ({currency})"), (620, "同点比较" if current else "较前日"), (800, "整店 ROI")]
        for x, label in columns:
            draw.text((x, y), label, font=f_small, fill=MUTED)
        y += 42
        for index, row in enumerate(rows, 1):
            draw.rounded_rectangle((48, y, WIDTH - 48, y + 74), radius=10, fill="#243247" if index % 2 else "#202D40")
            draw.text((62, y + 20), f"{index:02d}", font=f_body, fill=BLUE)
            store_name = str(row.get("store_name") or "未命名店铺")
            max_store_width = 325
            shown = store_name
            while shown and draw.textlength(shown, font=f_body) > max_store_width:
                shown = shown[:-1]
            if shown != store_name:
                shown = shown[:-1] + "…"
            draw.text((124, y + 10), shown, font=f_small, fill=INK)
            draw.text((124, y + 44), str(row.get("country") or "国家未设置"), font=f_small, fill=MUTED)
            amount = _fmt(row.get("sales_amount")) or "数据不完整"
            draw.text((438, y + 22), amount, font=_fit_font(draw, amount, 170), fill=INK)
            change = _num(row.get("change_percent"))
            change_color = MUTED if change is None else (GREEN if change >= 0 else RED)
            change_text = "缺同点基准" if current else (_fmt(row.get("change_percent"), "%") or "缺基准")
            roi_text = _fmt(row.get("roi"), " 倍") or _missing_roi(row)
            draw.text((620, y + 22), change_text, font=_fit_font(draw, change_text, 164), fill=change_color)
            draw.text((800, y + 22), roi_text, font=_fit_font(draw, roi_text, 100), fill=INK)
            y += 82
        y += 18
    if data.get("has_next"):
        draw.text((56, y), "此处仅列前20家店铺；授权范围完整合计见币种栏，完整排名请打开详情。", font=f_small, fill=MUTED)
        y += 32
    if not groups:
        draw.text((54, y), "当前范围暂无已入库销售记录，不表示销量为零。", font=f_small, fill=MUTED)
    y = height - 100
    draw.text((54, y), "数字保留两位小数；ROI 暂估，汇总 ROI 仅含有广告费记录的店铺。", font=f_small, fill=MUTED)
    draw.text((54, y + 30), "缺广告费/暂不可算不代表 ROI 为零；数据仅代表当前权限内已入库内容。", font=f_small, fill=MUTED)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
