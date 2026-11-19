"""Decimal-based ABC ranking and stable grade transitions."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


def _decimal(value: Any) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"amount must be finite and non-negative: {value!r}")
    return result


def rank_entities(
    rows: Iterable[Mapping[str, Any]],
    a_percent: Any = 80,
    b_percent: Any = 95,
) -> dict[Any, dict[str, Any]]:
    """Rank positive amounts; equal amounts always receive the same grade."""
    a = _decimal(a_percent) / Decimal(100)
    b = _decimal(b_percent) / Decimal(100)
    if not (Decimal(0) < a <= b <= Decimal(1)):
        raise ValueError("thresholds must satisfy 0 < a_percent <= b_percent <= 100")

    entities: list[tuple[Any, Decimal]] = []
    seen = set()
    for row in rows:
        identifier = row["id"]
        if identifier in seen:
            raise ValueError(f"duplicate entity id: {identifier!r}")
        seen.add(identifier)
        entities.append((identifier, _decimal(row["amount"])))

    total = sum((amount for _, amount in entities), Decimal(0))
    result: dict[Any, dict[str, Any]] = {}
    if total == 0:
        for identifier, _ in entities:
            result[identifier] = {"grade": "no_sales", "share": Decimal(0), "cumulative_share": Decimal(0)}
        return result

    eligible = sorted(((i, amount) for i, amount in entities if amount > 0), key=lambda item: (-item[1], str(item[0])))
    for identifier, amount in entities:
        if amount == 0:
            result[identifier] = {"grade": "no_sales", "share": Decimal(0), "cumulative_share": Decimal(0)}

    cumulative = Decimal(0)
    index = 0
    while index < len(eligible):
        end = index + 1
        amount = eligible[index][1]
        while end < len(eligible) and eligible[end][1] == amount:
            end += 1
        group_total = amount * (end - index)
        before_share = cumulative / total
        after_share = (cumulative + group_total) / total
        grade = "A" if before_share < a else "B" if before_share < b else "C"
        for identifier, entity_amount in eligible[index:end]:
            result[identifier] = {
                "grade": grade,
                "share": entity_amount / total,
                "cumulative_share": after_share,
            }
        cumulative += group_total
        index = end
    return result


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def transition_grade(
    candidate: str,
    previous: Mapping[str, Any] | None,
    cutoff_date: Any,
    stable_days: int = 3,
) -> dict[str, Any]:
    """Apply new/special grades immediately and require consecutive cutoffs for A/B/C changes."""
    if stable_days < 1:
        raise ValueError("stable_days must be at least 1")
    previous = previous or {}
    old_grade = previous.get("grade")
    old_streak = int(previous.get("candidate_streak", 0) or 0)
    old_candidate = previous.get("candidate_grade")
    old_date = _as_date(previous.get("cutoff_date"))
    current_date = _as_date(cutoff_date)

    def outcome(grade: Any, pending: Any, streak: int, changed: bool) -> dict[str, Any]:
        return {"grade": grade, "candidate_grade": pending, "candidate_streak": streak,
                "cutoff_date": cutoff_date, "changed": changed}

    abc = {"A", "B", "C"}
    if old_grade is None or old_grade == "new" or candidate not in abc:
        return outcome(candidate, None, 0, candidate != old_grade)
    if candidate == old_grade:
        return outcome(old_grade, None, 0, False)

    if current_date is None or old_date is None:
        return outcome(old_grade, candidate, 0, False)
    if current_date < old_date:
        return outcome(old_grade, candidate, 1, False)
    if current_date == old_date:
        # A retry for this cutoff cannot advance or replace the observed candidate.
        return outcome(old_grade, old_candidate, old_streak, False)

    consecutive = (current_date - old_date).days == 1
    streak = old_streak + 1 if consecutive and old_candidate == candidate else 1
    if streak >= stable_days:
        return outcome(candidate, None, 0, True)
    return outcome(old_grade, candidate, streak, False)
