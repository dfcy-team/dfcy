"""Bounded, read-only calculation cache; database revisions invalidate sessions."""
import atexit
import hashlib
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading

from django.conf import settings
from rest_framework.exceptions import ValidationError

from .summary_service import document_path, unpack_values

_lock = threading.Lock()
_process = None
_replies = None
_code_stamp = None


def stop():
    global _process
    if _process is not None:
        if _process.poll() is None:
            _process.kill()
        _process.wait(timeout=5)
        _process = None


atexit.register(stop)


def _read_lines(process, replies):
    try:
        for line in process.stdout:
            replies.put(json.loads(line))
    except (ValueError, OSError):
        pass
    replies.put(None)


def query(dataset, payload):
    global _process, _replies, _code_stamp
    state = dataset.accounting_state
    path = document_path(dataset)
    code = Path(__file__).parent
    stamps = [(f.stat().st_mtime_ns, f.stat().st_size) for f in [path, *[
        code / name for name in ('summary_native.cjs', 'summary_engine.cjs', 'summary_runtime.js', 'summary_composition.js', 'summary_cost_detail.cjs', 'summary_periods.cjs', 'summary_allocation.cjs', 'summary_order_ledger.cjs')]]]
    key = hashlib.sha256(json.dumps([dataset.tenant_id, dataset.pk, dataset.source_hash,
        state.revision, state.values, stamps], sort_keys=True).encode()).hexdigest()
    request = {'key': key, 'path': str(path), 'input': {
        **payload, 'state': unpack_values(state.values), 'sourceHash': dataset.source_hash,
        'sourceScope': dataset.metadata.get('database_scope')}}
    with _lock:
        try:
            if _code_stamp != stamps[1:]:
                stop()
                _code_stamp = stamps[1:]
            if _process is None or _process.poll() is not None:
                node = getattr(settings, 'FINANCE_SUMMARY_NODE', None) or shutil.which('node')
                if not node:
                    raise OSError()
                _process = subprocess.Popen([node, '--max-old-space-size=2048', str(code / 'summary_native.cjs')],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                _replies = queue.Queue()
                threading.Thread(target=_read_lines, args=(_process, _replies), daemon=True).start()
            _process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
            _process.stdin.flush()
            result = _replies.get(timeout=120)
            if result is None:
                raise OSError()
        except (OSError, queue.Empty):
            stop()
            raise ValidationError('财务查询未完成，请重试；未更改账务数据。')
    if not result.get('ok'):
        raise ValidationError(result.get('error', '财务计算失败。'))
    return {**result['result'], 'revision': state.revision, 'dataset': dataset.pk}
