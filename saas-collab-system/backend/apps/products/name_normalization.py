"""Safe normalization for SPU names derived from legacy item names.

Legacy imports carry the complete item name in ``ProductLegacyItem.product_name``
while the SPU name should describe the product family.  This module only
removes values explicitly supplied as the row's color/specification.  It does
not maintain a dictionary of arbitrary words to remove, which keeps ordinary
words in a product name intact (for example ``Blackberry`` is not a match for
the color ``black``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

from .standard_colors import STANDARD_COLORS


_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_WORD_CHAR = rf"A-Za-z0-9{_CJK}"
# Chinese marketplace names commonly concatenate the base and variant (for
# example ``硬壶铃蓝色-10LB``).  Permit a term after CJK text while retaining
# strict Latin/number boundaries so ``black`` still cannot match ``blackberry``.
_LEFT_BOUNDARY = r"(?<![A-Za-z0-9])"
_RIGHT_BOUNDARY = rf"(?![{_WORD_CHAR}])"
_SEPARATOR_CHARS = "_/|,，、;；:：·•‐‑‒–—"
_REMOVED_MARKER = "\ue000"
_OPEN_BRACKETS = "([{（【《"
_CLOSE_BRACKETS = ")] }）】》".replace(" ", "")

_STANDARD_COLOR_NAMES = dict(STANDARD_COLORS)
_STANDARD_COLOR_CODES_BY_NAME = {
    str(name).strip().casefold(): code for code, name in STANDARD_COLORS if str(name).strip()
}


@dataclass(frozen=True)
class NameNormalizationResult:
    """Result with enough evidence for a repair command to be auditable."""

    original: str
    normalized: str
    removed_terms: tuple[str, ...] = ()
    matched_color: bool = False
    matched_specification: bool = False
    reliable: bool = False
    reason: str = ""


def _nfkc(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _field_values(value: object) -> list[str]:
    """Return explicit values without splitting slash-based size values.

    ``M/XL`` is one specification in the legacy format and must be removed as
    one value.  Commas and pipes, on the other hand, are common delimiters for
    multiple color values, so those are split conservatively.
    """

    text = _nfkc(value)
    if not text or text == "0":
        return []
    return [part.strip() for part in re.split(r"[,，、;；|]+", text) if part.strip()]


def _term_pattern(term: str) -> re.Pattern[str] | None:
    term = _nfkc(term)
    if not term:
        return None
    cjk_length = len(re.findall(rf"[{_CJK}]", term))
    contains_cjk = cjk_length > 0
    # Single-character no-色 aliases (e.g. ``红``) are valid when separated
    # by a hyphen/bracket, but must not consume the first character of ordinary
    # words such as ``蓝牙``.
    right_boundary = (
        _RIGHT_BOUNDARY
        if not contains_cjk or cjk_length == 1
        else r"(?![A-Za-z0-9])"
    )

    # A color code can be written as either ``dark-blue`` or ``dark blue``;
    # dimensions and sizes commonly vary only in spacing around their
    # separators.  Keep letters/numbers literal so ``M`` cannot match inside
    # ``MM`` and ``black`` cannot match ``blackberry``.
    pieces: list[str] = []
    previous = ""
    for char in term:
        # Marketplace exports alternate between ``150cm`` and ``150 cm``.
        # Permit that harmless formatting difference at digit/unit boundaries,
        # but do not make arbitrary letters in a color code independently
        # matchable.
        if previous and previous.isalnum() and char.isalnum() and previous.isdigit() != char.isdigit():
            pieces.append(r"\s*")
        if char.isspace():
            pieces.append(r"\s*")
        elif char in "-_‐‑‒–—":
            pieces.append(r"[\s_\-‐‑‒–—]*")
        elif char in "/／":
            pieces.append(r"\s*[/／]\s*")
        elif char in "×xX*＊":
            pieces.append(r"\s*[×xX*＊]\s*")
        else:
            pieces.append(re.escape(char))
        previous = char
    return re.compile(_LEFT_BOUNDARY + "".join(pieces) + right_boundary, re.IGNORECASE)


def _color_terms(color_code: object, color_name: object = "") -> list[str]:
    values = _field_values(color_code)
    values.extend(_field_values(color_name))
    # A few legacy exports encode a multi-color row as ``blue/white``.  Slash
    # remains intact for specifications such as ``M/XL``; only color fields are
    # split into explicit individual aliases here.
    expanded_values: list[str] = []
    for value in values:
        expanded_values.append(value)
        if "/" in value or "／" in value:
            expanded_values.extend(part.strip() for part in re.split(r"[/／]", value) if part.strip())
    values = expanded_values
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        # The code is the authoritative imported value.  The standard display
        # name is an explicit alias only when that code is known to our color
        # dictionary; unknown custom codes remain exact matches.
        aliases = [value]
        key = value.casefold()
        if key in _STANDARD_COLOR_NAMES:
            aliases.append(_STANDARD_COLOR_NAMES[key])
        elif key in _STANDARD_COLOR_CODES_BY_NAME:
            aliases.append(_STANDARD_COLOR_CODES_BY_NAME[key])
        expanded_aliases = list(aliases)
        for alias in aliases:
            alias = _nfkc(alias)
            # Chinese exports are inconsistent about the trailing ``色``:
            # ``深灰`` and ``深灰色`` refer to the same explicit color value.
            # Add that spelling variant only for CJK aliases; arbitrary style
            # words are never introduced into the vocabulary.
            if alias and re.search(rf"[{_CJK}]", alias):
                if alias.endswith("色") and len(alias) > 1:
                    expanded_aliases.append(alias[:-1])
                elif not alias.endswith("色") and alias != "色":
                    expanded_aliases.append(alias + "色")
        for alias in expanded_aliases:
            alias = _nfkc(alias)
            marker = alias.casefold()
            if alias and marker not in seen:
                seen.add(marker)
                terms.append(alias)
    return terms


def _specification_terms(specification: object) -> list[str]:
    return _field_values(specification)


def _collect_matches(text: str, terms: Sequence[str]) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    # Prefer longer terms where aliases overlap (``dark-blue`` before
    # ``blue``), then resolve any remaining overlap deterministically.
    for term in sorted(terms, key=lambda item: (-len(item), item.casefold())):
        pattern = _term_pattern(term)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), term))
    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]), item[2].casefold())):
        if any(candidate[0] < end and candidate[1] > start for start, end, _ in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item[0])


def _clean_removed_name(value: str) -> str:
    """Remove dangling separators/wrappers without changing normal hyphens."""

    text = value
    # Only connectors touching a removed marker are discarded.  This keeps
    # ordinary punctuation in the base name (for example ``A/B``) unchanged.
    separator_class = re.escape(_SEPARATOR_CHARS + "- \t\r\n")
    text = re.sub(rf"[{separator_class}]*{re.escape(_REMOVED_MARKER)}[{separator_class}]*", " ", text)
    text = text.replace(_REMOVED_MARKER, " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Empty brackets can contain spaces or a connector that was just removed.
    # Repeat because nested wrappers are seen in marketplace exports.
    bracket_pairs = (("(", ")"), ("[", "]"), ("{", "}"), ("（", "）"), ("【", "】"), ("《", "》"))
    changed = True
    while changed:
        changed = False
        before = text
        for opening, closing in bracket_pairs:
            text = re.sub(rf"{re.escape(opening)}\s*{re.escape(closing)}", "", text)
        changed = text != before

    # Brackets left at an edge after a removed value are no longer useful.
    # Do not strip a bracket merely because it is at the edge: a base name can
    # legitimately end with a parenthesized qualifier.  Empty wrappers were
    # removed above; only separators introduced around a removed token belong
    # in this edge trim.
    edge = re.escape(_SEPARATOR_CHARS + "- ")
    text = re.sub(rf"^[{edge}]+", "", text)
    text = re.sub(rf"[{edge}]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_name_details(
    product_name: object,
    *,
    color_code: object = "",
    specification: object = "",
    color_name: object = "",
    color_terms: Sequence[str] | None = None,
    specification_terms: Sequence[str] | None = None,
) -> NameNormalizationResult:
    """Normalize one complete legacy item name with explicit variant fields.

    A result is marked reliable only when at least one explicit color or
    specification value was found as a complete token and the base name is
    non-empty.  Callers repairing old data can therefore skip rows for which
    the source evidence is insufficient.
    """

    original = _nfkc(product_name)
    if not original:
        return NameNormalizationResult(original, original, reason="empty_product_name")

    color_terms = list(color_terms) if color_terms is not None else _color_terms(color_code, color_name)
    specification_terms = (
        list(specification_terms)
        if specification_terms is not None
        else _specification_terms(specification)
    )
    color_matches = _collect_matches(original, color_terms)
    specification_matches = _collect_matches(original, specification_terms)

    # Resolve overlap between color/spec matches.  A value such as ``blue``
    # can be present in both fields in malformed source data; remove it once
    # and count it for both fields so the audit remains truthful.
    all_matches = color_matches + specification_matches
    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(all_matches, key=lambda item: (item[0], -(item[1] - item[0]), item[2].casefold())):
        if any(candidate[0] < end and candidate[1] > start for start, end, _ in selected):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: item[0])

    if not selected:
        return NameNormalizationResult(
            original,
            original,
            matched_color=False,
            matched_specification=False,
            reliable=False,
            reason="no_explicit_variant_match",
        )

    chars = list(original)
    for start, end, _ in reversed(selected):
        del chars[start:end]
        # Keep a marker until cleanup so only punctuation adjacent to the
        # removed value is treated as a dangling connector.
        chars.insert(start, _REMOVED_MARKER)
    normalized = _clean_removed_name("".join(chars))
    if not normalized:
        return NameNormalizationResult(
            original,
            original,
            tuple(item[2] for item in selected),
            any(item in color_matches for item in selected),
            any(item in specification_matches for item in selected),
            False,
            "name_only_contains_explicit_variant",
        )

    color_found = any(item in color_matches for item in selected)
    specification_found = any(item in specification_matches for item in selected)
    return NameNormalizationResult(
        original,
        normalized,
        tuple(item[2] for item in selected),
        color_found,
        specification_found,
        True,
        "",
    )


def normalize_spu_product_name(
    product_name: object,
    color_code: object = "",
    specification: object = "",
    *,
    color_name: object = "",
) -> str:
    """Return the SPU base name for a complete legacy item name.

    The public helper intentionally returns a string for use by serializers and
    import callers.  Repair workflows should use :func:`normalize_name_details`
    to inspect the reliability evidence before writing data.
    """

    return normalize_name_details(
        product_name,
        color_code=color_code,
        specification=specification,
        color_name=color_name,
    ).normalized


# Friendly aliases for callers/tests that use the shorter terminology.
normalize_product_name = normalize_spu_product_name
strip_variant_from_product_name = normalize_spu_product_name


def _dedupe_terms(terms: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _nfkc(term)
        marker = normalized.casefold()
        if normalized and marker not in seen:
            seen.add(marker)
            result.append(normalized)
    return result


def _item_fields(item: Mapping[str, object] | object) -> tuple[object, object, object, object]:
    if isinstance(item, Mapping):
        return (
            item.get("product_name", ""),
            item.get("color_code", ""),
            item.get("specification", ""),
            item.get("color_name", ""),
        )
    return (
        getattr(item, "product_name", ""),
        getattr(item, "color_code", ""),
        getattr(item, "specification", ""),
        getattr(item, "color_name", ""),
    )


def _names_related(left: str, right: str) -> bool:
    """Return whether a proposed base is plausibly the current SPU family."""

    left = _nfkc(left).casefold()
    right = _nfkc(right).casefold()
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    # Substring checks handle Chinese names well.  SequenceMatcher is only a
    # fallback for punctuation/case differences and requires a fairly strong
    # overlap so an unrelated product is never silently renamed.
    ratio = SequenceMatcher(None, left, right).ratio()
    if ratio < 0.62:
        return False
    left_chars = {char for char in left if char.isalnum() or "\u3400" <= char <= "\u9fff"}
    right_chars = {char for char in right if char.isalnum() or "\u3400" <= char <= "\u9fff"}
    return bool(left_chars and right_chars and len(left_chars & right_chars) >= 2)


_UNCONFIRMED_DIMENSION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"\d+(?:\.\d+)?\s*(?:mm|cm|m|kg|g|lb|lbs|oz|ft|inch)"
    r"(?:\s*[×xX*]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|kg|g|lb|lbs|oz|ft|inch))?"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_UNCONFIRMED_DIMENSION_PAIR_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*[×xX*]\s*\d+(?:\.\d+)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_UNCONFIRMED_SIZE_LABEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:特大号|加大号|超大号|小号|中号|大号|XXXS|XXS|XXL|XXXL|XS|XL|S|M|L)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _unconfirmed_variant_like_terms(value: str) -> list[str]:
    """Find variant-looking fragments for which no explicit field evidence exists.

    This is intentionally a narrow fail-safe detector, not a removal
    dictionary.  A remaining dimension/size-looking fragment causes a repair
    to be skipped rather than guessed away; styles such as 套装/枕套/脚凳 are
    not included and therefore remain valid base-name words.
    """

    matches = []
    for pattern in (
        _UNCONFIRMED_DIMENSION_PATTERN,
        _UNCONFIRMED_DIMENSION_PAIR_PATTERN,
        _UNCONFIRMED_SIZE_LABEL_PATTERN,
    ):
        matches.extend(match.group(0) for match in pattern.finditer(value))
    return sorted(set(matches), key=lambda item: (value.casefold().find(item.casefold()), item.casefold()))


def consensus_spu_product_name(
    items: Iterable[Mapping[str, object] | object],
    *,
    reference_name: object = "",
    color_name_by_code: Mapping[str, object] | None = None,
) -> tuple[str | None, dict[str, object]]:
    """Choose one deterministic base name from rows belonging to an SPU.

    The most frequent reliable candidate wins.  Ties prefer the shortest
    candidate (the conservative choice that cannot retain an extra variant),
    then case-folded lexical order, making the result independent of import
    row order.  The returned evidence is suitable for dry-run/audit output.
    """

    rows = list(items)
    if not rows:
        return None, {"reliable": False, "reason": "no_reliable_candidate", "rows": 0}

    # Source exports occasionally associate a row with the wrong color or
    # specification.  Build one explicit variant vocabulary for the entire
    # SPU, then remove that vocabulary from every complete 商品名称.  No
    # arbitrary style words are added here: only values present in a row's
    # explicit color/specification columns are eligible.
    group_color_terms: list[str] = []
    group_specification_terms: list[str] = []
    display_names = {
        _nfkc(code).casefold(): value
        for code, value in (color_name_by_code or {}).items()
        if _nfkc(code)
    }
    for item in rows:
        _name, color, specification, color_name = _item_fields(item)
        if not color_name and color:
            color_name = display_names.get(_nfkc(color).casefold(), "")
        group_color_terms.extend(_color_terms(color, color_name))
        group_specification_terms.extend(_specification_terms(specification))
    group_color_terms = _dedupe_terms(group_color_terms)
    group_specification_terms = _dedupe_terms(group_specification_terms)
    if not group_color_terms and not group_specification_terms:
        return None, {
            "reliable": False,
            "reason": "no_explicit_variant_terms",
            "rows": len(rows),
            "color_terms": 0,
            "specification_terms": 0,
        }

    candidates: list[tuple[str, NameNormalizationResult]] = []
    for item in rows:
        name, _color, _specification, _color_name = _item_fields(item)
        result = normalize_name_details(
            name,
            color_terms=group_color_terms,
            specification_terms=group_specification_terms,
        )
        # A row that is already the group base contributes to support even if
        # it contains no variant token.  Empty names remain unusable evidence.
        if result.reliable or result.normalized:
            candidates.append((result.normalized, result))

    if not candidates or not any(result.reliable for _candidate, result in candidates):
        return None, {"reliable": False, "reason": "no_reliable_candidate", "rows": len(rows)}

    counts = Counter(candidate for candidate, _ in candidates)
    best_count = max(counts.values())
    total_rows = len(rows)
    # A repair is safe only when a clear majority agrees.  For a two-row SPU,
    # both rows must agree; with larger groups a 60% floor avoids selecting one
    # malformed/foreign row as the family name.
    required_support = 1 if total_rows == 1 else max(2, (total_rows * 6 + 9) // 10)
    if best_count < required_support:
        return None, {
            "reliable": False,
            "reason": "low_consensus_support",
            "rows": total_rows,
            "candidate_count": len(counts),
            "support": best_count,
            "required_support": required_support,
            "color_terms": len(group_color_terms),
            "specification_terms": len(group_specification_terms),
        }
    best = sorted(
        (candidate for candidate, count in counts.items() if count == best_count),
        key=lambda candidate: (len(candidate), candidate.casefold()),
    )[0]
    result = next(result for candidate, result in candidates if candidate == best)
    residual = _collect_matches(best, [*group_color_terms, *group_specification_terms])
    if residual:
        return None, {
            "reliable": False,
            "reason": "residual_explicit_variant_term",
            "rows": total_rows,
            "candidate_count": len(counts),
            "support": best_count,
            "required_support": required_support,
            "color_terms": len(group_color_terms),
            "specification_terms": len(group_specification_terms),
            "residual_terms": [item[2] for item in residual],
        }
    unconfirmed = _unconfirmed_variant_like_terms(best)
    if unconfirmed:
        return None, {
            "reliable": False,
            "reason": "unconfirmed_variant_like_term",
            "rows": total_rows,
            "candidate_count": len(counts),
            "support": best_count,
            "required_support": required_support,
            "color_terms": len(group_color_terms),
            "specification_terms": len(group_specification_terms),
            "unconfirmed_terms": unconfirmed,
        }
    if reference_name and not _names_related(_nfkc(reference_name), best):
        return None, {
            "reliable": False,
            "reason": "reference_name_unrelated",
            "rows": total_rows,
            "candidate_count": len(counts),
            "support": best_count,
            "required_support": required_support,
            "color_terms": len(group_color_terms),
            "specification_terms": len(group_specification_terms),
        }
    return best, {
        "reliable": True,
        "reason": "",
        "rows": total_rows,
        "candidate_count": len(counts),
        "support": best_count,
        "required_support": required_support,
        "color_terms": len(group_color_terms),
        "specification_terms": len(group_specification_terms),
        "removed_terms": list(result.removed_terms),
    }
