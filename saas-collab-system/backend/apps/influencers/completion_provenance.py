"""Writer-owned completion marker; legacy free-text reasons are never authority."""
import json
import re
from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac

PREFIX = 'api_video_verified_v2:'
SALT = 'influencers.sample_completion_provenance.v2'

def _payload(tenant_id, sample_id, actor_id, raw_id, external_id):
    ids = (tenant_id, sample_id, actor_id, raw_id)
    if any(type(value) is not int or not 0 < value <= 9223372036854775807 for value in ids):
        raise ValueError('Invalid provenance identity.')
    if not isinstance(external_id, str) or not 1 <= len(external_id) <= 160:
        raise ValueError('Invalid external video identity.')
    return json.dumps([*ids, external_id], ensure_ascii=False, separators=(',', ':'))

def _signature(payload, secret):
    return salted_hmac(SALT, payload, secret=secret, algorithm='sha256').hexdigest()[:32]

def completion_reason(*, tenant_id, sample_id, actor_id, raw_id, external_id):
    payload = _payload(tenant_id, sample_id, actor_id, raw_id, external_id)
    reason = f'{PREFIX}{raw_id}:{external_id}:{_signature(payload, settings.SECRET_KEY)}'
    assert len(reason) <= 240
    return reason

def parse_completion_reason(reason, *, tenant_id, sample_id, actor_id):
    """Return raw identity and writer verification; malformed markers fail closed."""
    if not isinstance(reason, str):
        return None
    if reason.startswith(PREFIX):
        try:
            raw, rest = reason[len(PREFIX):].split(':', 1)
            external_id, signature = rest.rsplit(':', 1)
        except ValueError:
            return None
        version = 2
    elif reason.startswith('api_video_verified:'):
        try:
            raw, external_id = reason[len('api_video_verified:'):].split(':', 1)
        except ValueError:
            return None
        version = 1
    else:
        return None
    if not re.fullmatch(r'[1-9][0-9]{0,18}', raw) or int(raw) > 9223372036854775807:
        return None
    try:
        payload = _payload(tenant_id, sample_id, actor_id, int(raw), external_id)
    except ValueError:
        return None
    verified = False
    if version == 2 and re.fullmatch(r'[0-9a-f]{32}', signature):
        verified = any(constant_time_compare(signature, _signature(payload, secret))
            for secret in [settings.SECRET_KEY, *getattr(settings, 'SECRET_KEY_FALLBACKS', [])])
    return int(raw), external_id, verified
