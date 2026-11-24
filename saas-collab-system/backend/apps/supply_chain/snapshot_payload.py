"""Lossless storage of large snapshot evidence fields."""
import base64
import json
import zlib

_MARKER = "__zlib_json_v1__"
_FIELDS = ("source_run_ids", "sales_archive_issues")


def pack_payload(payload):
    result = payload.copy()
    for name in _FIELDS:
        value = payload.get(name)
        if not isinstance(value, (list, dict)) or not value:
            continue
        if isinstance(value, dict) and _MARKER in value:
            continue
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) < 512:
            continue
        encoded = base64.b64encode(zlib.compress(raw, 1)).decode("ascii")
        if len(encoded) + len(_MARKER) + 7 < len(raw):
            result[name] = {_MARKER: encoded}
    return result


def unpack_payload(payload):
    result = payload
    for name in _FIELDS:
        value = payload.get(name)
        if isinstance(value, dict) and value.keys() == {_MARKER}:
            if result is payload:
                result = payload.copy()
            result[name] = json.loads(zlib.decompress(base64.b64decode(value[_MARKER], validate=True)))
    return result
