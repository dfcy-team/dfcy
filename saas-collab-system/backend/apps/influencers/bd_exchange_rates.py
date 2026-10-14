"""Validated BD currency-to-CNY schedules, never a legacy rate write path."""

from datetime import date
from decimal import Decimal
import re

from django.core.exceptions import ValidationError

from apps.common.security import sanitize_sensitive_data


BD_EXCHANGE_RATES_CONFIG_KEY = "influencers.bd.exchange_rates"
BD_EXCHANGE_RATE_CURRENCIES = frozenset({"PHP", "MYR", "THB", "USD"})
MAX_BD_EXCHANGE_RATES = 1000
_RATE_PATTERN = re.compile(r"[0-9]{1,10}(?:\.[0-9]{1,10})?")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def validate_bd_exchange_rate_definition(definition):
    if (
        definition.config_key != BD_EXCHANGE_RATES_CONFIG_KEY
        or definition.scope_type != "tenant"
        or definition.value_type != "json"
        or definition.is_sensitive
        or definition.requires_approval
    ):
        raise ValidationError({
            BD_EXCHANGE_RATES_CONFIG_KEY: "BD FX definition must be tenant/json/non-sensitive without approval.",
        })


def validate_bd_exchange_rates(value):
    """Return a detached schedule without coercing or rounding rate strings."""
    def invalid(message):
        raise ValidationError({BD_EXCHANGE_RATES_CONFIG_KEY: message})

    if not isinstance(value, dict) or set(value) != {"rates"}:
        invalid("BD exchange rates must be an object containing only rates.")
    rates = value["rates"]
    if not isinstance(rates, list) or len(rates) > MAX_BD_EXCHANGE_RATES:
        invalid("rates must be a list containing at most 1000 entries.")
    seen = set()
    validated = []
    for index, row in enumerate(rates):
        prefix = f"rates[{index}]"
        required = {"currency", "rate", "effective_from"}
        if not isinstance(row, dict) or not required <= set(row) or set(row) - (required | {"note"}):
            invalid(f"{prefix} must contain currency, rate, effective_from and optional note only.")
        currency = row["currency"]
        if not isinstance(currency, str) or currency not in BD_EXCHANGE_RATE_CURRENCIES:
            invalid(f"{prefix}.currency must be PHP, MYR, THB or USD; CNY is always identity 1.")
        rate = row["rate"]
        if not isinstance(rate, str) or _RATE_PATTERN.fullmatch(rate) is None:
            invalid(f"{prefix}.rate must be a decimal string with at most 10 integer and 10 fractional digits.")
        parsed_rate = Decimal(rate)
        if not parsed_rate.is_finite() or parsed_rate <= 0:
            invalid(f"{prefix}.rate must be finite and positive.")
        effective_from = row["effective_from"]
        if not isinstance(effective_from, str) or _DATE_PATTERN.fullmatch(effective_from) is None:
            invalid(f"{prefix}.effective_from must use YYYY-MM-DD between 1900 and 2100.")
        try:
            parsed_date = date.fromisoformat(effective_from)
        except ValueError:
            invalid(f"{prefix}.effective_from must be a valid calendar date.")
        if not 1900 <= parsed_date.year <= 2100:
            invalid(f"{prefix}.effective_from must be between 1900 and 2100.")
        note = row.get("note", "")
        if not isinstance(note, str) or len(note) > 240:
            invalid(f"{prefix}.note must be a string of at most 240 characters.")
        pair = (currency, effective_from)
        if pair in seen:
            invalid("Duplicate currency and effective_from entries are prohibited.")
        seen.add(pair)
        validated.append(dict(row))
    result = {"rates": validated}
    if sanitize_sensitive_data(result) != result:
        invalid("Credential, token, cookie, session, and secret values are prohibited.")
    return result
