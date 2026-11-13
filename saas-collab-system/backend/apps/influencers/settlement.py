"""Independent affiliate settlement facts; never infer from fulfillment."""

SETTLED = "\u5df2\u7ed3\u7b97"
INELIGIBLE = "\u4e0d\u7b26\u5408\u6761\u4ef6"
TO_SETTLE = "\u5f85\u7ed3\u7b97"
AWAITING_PAYMENT = "\u5f85\u4ed8\u6b3e"
SETTLEMENT_CHOICES = ((SETTLED, SETTLED), (INELIGIBLE, INELIGIBLE), (TO_SETTLE, TO_SETTLE),
                      (AWAITING_PAYMENT, AWAITING_PAYMENT))
NO_REFUND_MARKERS = frozenset({"\u5426", "no", "false", "0", "n"})
REFUND_MARKERS = frozenset({"\u662f", "yes", "true", "1", "y"})


def normalize_settlement_status(value, *, csv=False):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("settlement_status: unknown_enum")
    raw = value.strip()
    if not raw:
        return None
    mapping = {"settled": SETTLED, "ineligible": INELIGIBLE, "to-settle": TO_SETTLE,
               "awaiting payment": AWAITING_PAYMENT,
               SETTLED: SETTLED, INELIGIBLE: INELIGIBLE, TO_SETTLE: TO_SETTLE,
               AWAITING_PAYMENT: AWAITING_PAYMENT}
    if csv:
        mapping["\u5f85\u786e\u8ba4"] = TO_SETTLE
    try:
        return mapping[raw.casefold()]
    except KeyError:
        raise ValueError("settlement_status: unknown_enum") from None


def refund_marker(value):
    return "" if value is None else str(value).strip().casefold()
