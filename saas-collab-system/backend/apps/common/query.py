from rest_framework.exceptions import ValidationError


def positive_int(value, *, default, maximum=None):
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Pagination values must be integers.")
    if parsed < 1:
        raise ValidationError("Pagination value must be a positive integer.")
    if maximum is not None and parsed > maximum:
        raise ValidationError(f"Pagination value must not exceed {maximum}.")
    return parsed


def pagination_query(request, *, default_size=20):
    return (
        positive_int(request.query_params.get("page"), default=1),
        positive_int(request.query_params.get("page_size"), default=default_size, maximum=100),
    )
