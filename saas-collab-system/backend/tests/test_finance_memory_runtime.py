import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.finance import summary_native as native
from apps.finance.summary_memory import MemoryBudgetExceeded


@pytest.fixture
def calculator(monkeypatch, tmp_path, settings):
    native.stop()
    path = tmp_path / 'source.gz'
    path.write_bytes(b'synthetic')
    monkeypatch.setattr(native, 'document_path', lambda dataset: path)
    monkeypatch.setattr(native, 'unpack_values', lambda values: values)
    settings.FINANCE_SUMMARY_NODE = 'synthetic-node'
    dataset = SimpleNamespace(tenant_id=1, pk=1, source_hash='synthetic', metadata={},
                              accounting_state=SimpleNamespace(revision=1, values={}))
    yield dataset
    native.stop()


def test_query_uses_budget_and_returns_unchanged_result(calculator, monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.stdin = io.StringIO()
    process.stdout = io.StringIO('{"ok":true,"result":{"amount":"123.45"}}\n')
    spawn = Mock(return_value=process)
    monkeypatch.setattr(native.subprocess, 'Popen', spawn)
    monkeypatch.setattr(native, 'node_heap_mb', lambda configured=2048: min(configured, 700))
    result = native.query(calculator, {'action': 'table'})
    assert result == {'amount': '123.45', 'revision': 1, 'dataset': 1}
    assert '--max-old-space-size=700' in spawn.call_args.args[0]


def test_successful_query_releases_only_idle_vm(calculator, monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.stdin = io.StringIO()
    process.stdout = io.StringIO('{"ok":true,"result":{"amount":"123.45"}}\n')
    monkeypatch.setattr(native.subprocess, 'Popen', Mock(return_value=process))
    timer = Mock()
    schedule = Mock(return_value=timer)
    monkeypatch.setattr(native.threading, 'Timer', schedule)
    assert native.query(calculator, {'action': 'table'})['amount'] == '123.45'
    process.kill.assert_not_called()
    assert schedule.call_args.args[0] == 60 and timer.daemon is True
    timer.start.assert_called_once()
    schedule.call_args.args[1]()
    process.kill.assert_called_once()
    assert native._process is None and native._session_key is None


def test_expired_idle_callback_cannot_interrupt_new_request(calculator, monkeypatch):
    import threading
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(native, '_process', process)
    timers, callbacks = [], []
    def schedule(seconds, callback):
        timer = Mock()
        timers.append(timer)
        callbacks.append(callback)
        return timer
    monkeypatch.setattr(native.threading, 'Timer', schedule)
    with native._lock:
        native._release_when_idle()
        started = threading.Event()
        def expire():
            started.set()
            callbacks[0]()
        thread = threading.Thread(target=expire)
        thread.start()
        assert started.wait(timeout=1)
        process.kill.assert_not_called()
        native._release_when_idle()
    thread.join(timeout=2)
    assert not thread.is_alive()
    timers[0].cancel.assert_called_once()
    process.kill.assert_not_called()
    callbacks[1]()
    process.kill.assert_called_once()


def test_insufficient_memory_never_starts_vm(calculator, monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(native.subprocess, 'Popen', spawn)
    def insufficient(configured=2048):
        raise MemoryBudgetExceeded()
    monkeypatch.setattr(native, 'node_heap_mb', insufficient)
    with pytest.raises(native.CalculationMemoryLimit):
        native.query(calculator, {'action': 'table'})
    spawn.assert_not_called()
    assert native._lock.acquire(blocking=False)
    native._lock.release()


def test_source_guard_waits_for_old_vm_and_releases_lock_on_failure(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(native, '_process', process)
    with pytest.raises(RuntimeError):
        with native.materialization_guard():
            process.kill.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            assert native._process is None
            raise RuntimeError('source failed')
    assert native._lock.acquire(blocking=False)
    native._lock.release()


def test_rebuild_engine_reports_same_memory_budget_error(monkeypatch, settings):
    from apps.finance import summary_service as service
    from apps.finance import summary_memory
    settings.FINANCE_SUMMARY_NODE = 'synthetic-node'
    spawn = Mock()
    monkeypatch.setattr(service.subprocess, 'run', spawn)
    def insufficient():
        raise MemoryBudgetExceeded()
    monkeypatch.setattr(summary_memory, 'node_heap_mb', insufficient)
    with pytest.raises(native.CalculationMemoryLimit):
        service.engine(SimpleNamespace(source_hash='synthetic'), {'action': 'inspect'})
    spawn.assert_not_called()
