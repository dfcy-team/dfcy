"""Pure rules for combining revenue and unit ABC classifications.

Ranking and persistence are intentionally caller responsibilities. The caller
passes the already ranked revenue and unit grades for one country/entity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping, Any


Grade = Literal["A", "B", "C", "new", "no_sales", "unavailable"]
RankGrade = Literal["A", "B", "C", "no_sales", "unavailable"]
Maturity = Literal["mature", "new", "unknown"]


@dataclass(frozen=True)
class ABCThresholds:
    """Conservative, immutable evidence thresholds for comprehensive ABC."""

    active_weeks_12_min: int = 6
    active_weeks_4_min: int = 3
    single_order_share_anomaly: Decimal = Decimal("0.30")
    single_day_share_anomaly: Decimal = Decimal("0.40")

    def __post_init__(self) -> None:
        if self.active_weeks_12_min < 0 or self.active_weeks_4_min < 0:
            raise ValueError("active-week thresholds must be non-negative")
        for name in ("single_order_share_anomaly", "single_day_share_anomaly"):
            value = Decimal(str(getattr(self, name)))
            if not Decimal(0) <= value <= Decimal(1):
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, value)


DEFAULT_THRESHOLDS = ABCThresholds()
_VALID_RANK_GRADES = {"A", "B", "C", "no_sales", "unavailable"}


def _decimal(value: Any, name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be numeric or None") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def evaluate_comprehensive_abc(
    *,
    revenue_grade: RankGrade | str,
    units_grade: RankGrade | str,
    active_weeks_last12: int | None,
    active_weeks_last4: int | None,
    history_complete: bool,
    maturity: Maturity | str,
    total_units: int | float | Decimal | None = None,
    max_single_order_units: int | float | Decimal | None = None,
    max_single_day_units: int | float | Decimal | None = None,
    thresholds: ABCThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """Return the comprehensive grade, a reference grade, and auditable basis.

    `history_complete` must be false when sales days/weeks are missing or the
    source window is not fully validated. Missing active-week counts are also
    treated as incomplete. Concentration is only a suspected anomaly signal;
    it does not assert that a promotion occurred.
    """
    if revenue_grade not in _VALID_RANK_GRADES:
        raise ValueError(f"invalid revenue_grade: {revenue_grade}")
    if units_grade not in _VALID_RANK_GRADES:
        raise ValueError(f"invalid units_grade: {units_grade}")
    if maturity not in {"mature", "new", "unknown"}:
        raise ValueError(f"invalid maturity: {maturity}")
    for name, value in (("active_weeks_last12", active_weeks_last12), ("active_weeks_last4", active_weeks_last4)):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ValueError(f"{name} must be a non-negative integer or None")
    if active_weeks_last12 is not None and active_weeks_last4 is not None and active_weeks_last4 > active_weeks_last12:
        raise ValueError("active_weeks_last4 cannot exceed active_weeks_last12")

    total = _decimal(total_units, "total_units")
    order = _decimal(max_single_order_units, "max_single_order_units")
    day = _decimal(max_single_day_units, "max_single_day_units")
    order_anomaly = total is not None and total > 0 and order is not None and order / total >= thresholds.single_order_share_anomaly
    day_anomaly = total is not None and total > 0 and day is not None and day / total >= thresholds.single_day_share_anomaly
    sustained = (
        active_weeks_last12 is not None
        and active_weeks_last4 is not None
        and active_weeks_last12 >= thresholds.active_weeks_12_min
        and active_weeks_last4 >= thresholds.active_weeks_4_min
    )

    basis: dict[str, Any] = {
        "revenue_grade": revenue_grade,
        "units_grade": units_grade,
        "maturity": maturity,
        "history_complete": bool(history_complete),
        "active_weeks_last12": active_weeks_last12,
        "active_weeks_last4": active_weeks_last4,
        "sustained": sustained,
        "total_units": str(total) if total is not None else None,
        "max_single_order_units": str(order) if order is not None else None,
        "max_single_day_units": str(day) if day is not None else None,
        "single_order_share_anomaly": order_anomaly,
        "single_day_share_anomaly": day_anomaly,
        "thresholds": {
            **asdict(thresholds),
            "single_order_share_anomaly": str(thresholds.single_order_share_anomaly),
            "single_day_share_anomaly": str(thresholds.single_day_share_anomaly),
        },
    }
    reasons: list[str] = []

    if maturity == "new":
        return {"grade": "new", "reference_grade": "new", "reason_codes": ["new_product_observation"], "basis": basis}
    if maturity == "unknown":
        return {"grade": "unavailable", "reference_grade": "unavailable", "reason_codes": ["maturity_unknown"], "basis": basis}

    complete = bool(history_complete) and active_weeks_last12 is not None and active_weeks_last4 is not None
    if revenue_grade == "no_sales" and units_grade == "no_sales":
        reasons.append("no_positive_net_sales_or_units")
        if complete:
            return {"grade": "no_sales", "reference_grade": "no_sales", "reason_codes": reasons, "basis": basis}
        reasons.append("incomplete_sales_history")
        return {"grade": "unavailable", "reference_grade": "unavailable", "reason_codes": reasons, "basis": basis}

    if not complete:
        reasons.append("incomplete_sales_history")
        # An incomplete window cannot produce a formal grade. Do not promote
        # double-C into B: without complete coverage there is no basis to say
        # that the item has regular business activity.
        ref = _candidate_grade(revenue_grade, units_grade, sustained, order_anomaly or day_anomaly, reasons)
        if ref == "C":
            ref = "unavailable"
            reasons.append("incomplete_history_prevents_reference_C")
        return {"grade": "unavailable", "reference_grade": ref, "reason_codes": reasons, "basis": basis}

    if "unavailable" in (revenue_grade, units_grade):
        reasons.append("abc_component_unavailable")
        return {"grade": "unavailable", "reference_grade": "unavailable", "reason_codes": reasons, "basis": basis}

    candidate = _candidate_grade(revenue_grade, units_grade, sustained, order_anomaly or day_anomaly, reasons)
    if candidate == "C":
        reasons.append("both_revenue_and_units_C")
    return {"grade": candidate, "reference_grade": candidate, "reason_codes": reasons, "basis": basis}


def _candidate_grade(
    revenue_grade: str,
    units_grade: str,
    sustained: bool,
    anomaly: bool,
    reasons: list[str],
) -> str:
    if revenue_grade == "A":
        reasons.append("revenue_A")
        return "A"
    if units_grade == "A":
        if anomaly:
            reasons.append("suspected_order_or_day_concentration")
        if sustained and not anomaly:
            reasons.append("units_A_with_sustained_sales")
            return "A"
        reasons.append("units_A_without_sufficient_clean_continuity")
        return "B"
    if "B" in (revenue_grade, units_grade):
        reasons.append("revenue_or_units_B")
        return "B"
    if revenue_grade == "C" and units_grade == "C":
        return "C"
    reasons.append("abc_components_not_decisive")
    return "unavailable"
