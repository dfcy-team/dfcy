"""Bounded, read-only calculation cache; database revisions invalidate sessions."""
import atexit
from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from django.conf import settings
from rest_framework.exceptions import ValidationError

from .summary_service import document_path, unpack_values
from .summary_memory import node_heap_mb, MemoryBudgetExceeded

_lock = threading.Lock()
_process = None
_replies = None
_code_stamp = None
_tenant_id = None
_session_key = None
_idle_timer = None
logger = logging.getLogger(__name__)


class CalculationBusy(ValidationError):
    default_detail = '计算资源正忙，任务将在后台自动重试。'


class CalculationMemoryLimit(ValidationError):
    default_detail = '财务计算内存预算不足，请缩小查询范围；原结果保持不变。'


class CalculationTimeout(ValidationError):
    default_detail = '财务计算超过120秒，原结果保持不变，请重新查询。'


def stop():
    global _process, _tenant_id, _session_key, _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()
        _idle_timer = None
    if _process is not None:
        if _process.poll() is None:
            _process.kill()
        _process.wait(timeout=5)
        _process = None
    _tenant_id = None
    _session_key = None


def _release_when_idle():
    global _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()
        _idle_timer = None
    process = _process
    if process is None or process.poll() is not None:
        return

    def release():
        with _lock:
            if _idle_timer is timer and _process is process:
                stop()

    timer = threading.Timer(60, release)
    timer.daemon = True
    _idle_timer = timer
    timer.start()


atexit.register(stop)


@contextmanager
def materialization_guard():
    if not _lock.acquire(timeout=30):
        raise CalculationBusy()
    try:
        stop()
        yield
    finally:
        _lock.release()


def _read_lines(process, replies):
    try:
        for line in process.stdout:
            replies.put(json.loads(line))
    except (ValueError, OSError):
        pass
    replies.put(None)


def query(dataset, payload):
    global _process, _replies, _code_stamp, _tenant_id, _session_key
    state = dataset.accounting_state
    path = document_path(dataset)
    code = Path(__file__).parent
    stamps = [(f.stat().st_mtime_ns, f.stat().st_size) for f in [path, *[
        code / name for name in ('summary_native.cjs', 'summary_flow_view.cjs', 'summary_engine.cjs', 'summary_participation.js', 'summary_accounting_rules.json', 'summary_runtime.js', 'summary_composition.js', 'summary_cost_detail.cjs', 'summary_periods.cjs', 'summary_allocation.cjs', 'summary_order_ledger.cjs')]]]
    key = hashlib.sha256(json.dumps([dataset.tenant_id, dataset.pk, dataset.source_hash,
        state.revision, state.values, stamps], sort_keys=True).encode()).hexdigest()
    request = {'key': key, 'path': str(path), 'input': {
        **payload, 'state': unpack_values(state.values), 'sourceHash': dataset.source_hash,
        'sourceScope': dataset.metadata.get('database_scope')}}
    started = time.monotonic()
    if not _lock.acquire(timeout=30):
        raise CalculationBusy()
    lock_wait_ms = round((time.monotonic()-started)*1000, 2)
    try:
        try:
            # Release the old VM before loading another tenant, batch or revision.
            if _session_key is not None and _session_key != key:
                stop()
            if _code_stamp != stamps[1:]:
                stop()
                _code_stamp = stamps[1:]
            if _process is None or _process.poll() is not None:
                node = getattr(settings, 'FINANCE_SUMMARY_NODE', None) or shutil.which('node')
                if not node:
                    raise OSError()
                configured_heap_mb = 1024 if dataset.metadata.get('direct_query') else 2048
                heap_mb = node_heap_mb(configured_heap_mb)
                _process = subprocess.Popen([node, f'--max-old-space-size={heap_mb}', str(code / 'summary_native.cjs')],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                _tenant_id = dataset.tenant_id
                _session_key = key
                _replies = queue.Queue()
                threading.Thread(target=_read_lines, args=(_process, _replies), daemon=True).start()
            _process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
            _process.stdin.flush()
            result = _replies.get(timeout=120)
            if result is None:
                raise OSError()
        except MemoryBudgetExceeded:
            stop()
            raise CalculationMemoryLimit() from None
        except queue.Empty:
            stop()
            raise CalculationTimeout() from None
        except OSError:
            stop()
            raise ValidationError('财务查询未完成，请重试；未更改账务数据。')
    finally:
        try:
            _release_when_idle()
        finally:
            _lock.release()
    timings = {'lock_wait_ms': lock_wait_ms}
    for name in ('read_decode_ms','validate_ms','prepare_ms','restore_ms','vm_ms','directory_ms','open_ms','calculate_ms'):
        value = result.get('timings',{}).get(name)
        if isinstance(value,(int,float)) and 0 <= value < 900000:
            timings[name] = round(value,2)
    logger.info('Finance query timings: %s', json.dumps(timings,sort_keys=True))
    if not result.get('ok'):
        raise ValidationError(result.get('error', '财务计算失败。'))
    return {**result['result'], 'revision': state.revision, 'dataset': dataset.pk}
