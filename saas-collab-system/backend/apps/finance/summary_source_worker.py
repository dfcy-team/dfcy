"""One-shot source reader; exits before the calculation VM is loaded."""
import json
import logging
import re
import sys
from types import SimpleNamespace


def main():
    logging.disable(logging.CRITICAL)
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from .summary_read_query import materialize_source, SourceReadTimeout
    from .summary_scopes import store_ids
    from .summary_service import private_root, require_access
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        request = json.loads(raw)
        if not re.fullmatch(r'read-query-[a-f0-9]{64}\.html\.gz', request['filename']):
            raise ValueError()
        if not re.fullmatch(r'[a-f0-9]{32}', request['token']):
            raise ValueError()
        user = get_user_model().objects.get(pk=request['user'], tenant_id=request['tenant'], is_active=True)
        require_access(user)
        if not set(request['scope']['stores']).issubset(set(store_ids(user))):
            raise ValueError()
        materialize_source(user, SimpleNamespace(document_file=request['document_file']),
            {'scope': request['scope']}, private_root()/request['filename'], request['token'])
        reply = {'ok': True}
    except SourceReadTimeout:
        reply = {'ok': False, 'code': 'SOURCE_READ_TIMEOUT'}
    except Exception:
        reply = {'ok': False, 'code': 'SOURCE_READ_FAILED'}
    print(json.dumps(reply))


if __name__ == '__main__':
    main()
